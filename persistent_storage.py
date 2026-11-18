#!/usr/bin/env python3
"""
SQLite based persistent storage shared by the sensor workers (writers) and the
web server (reader).

All processes open the same database file. WAL journal mode allows the web
server to read while a sensor worker is writing, and a busy timeout makes the
(rare) concurrent writes wait for each other instead of failing.

Configuration (environment variables, all optional):
  AQ_DB_PATH             path of the database file
                         (default: aq_dashboard.db next to this file)
  AQ_DB_RETENTION_DAYS   samples older than this are deleted periodically by
                         the writers so that the database does not fill the
                         SD card (default: 30, 0 disables the clean-up)
"""

import json
import os
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Iterable, List, Optional, Tuple

from logger_configurator import LoggerConfigurator


def _db_to_energy(level):
    return None if level is None else 10.0 ** (level / 10.0)


ENERGY_PREFIX = "energy("


def column_expression(spec: str) -> Tuple[str, str]:
    """Column spec -> (column, SQL expression): "x" or "energy(x)" (10^(x/10), for sound levels)."""
    if spec.startswith(ENERGY_PREFIX) and spec.endswith(")"):
        column = spec[len(ENERGY_PREFIX):-1]
        return column, f'db_to_energy("{column}")'
    return spec, f'"{spec}"'


class _SQLiteStorage:
    DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aq_dashboard.db")
    DEFAULT_RETENTION_DAYS = 30
    # Only samples newer than this are considered current by the readers
    MAX_SAMPLE_AGE_SEC = 10 * 60
    BUSY_TIMEOUT_SEC = 5
    PRUNE_INTERVAL_SEC = 60 * 60

    class Point(Enum):
        """Table names (the former InfluxDB point names; the PMSA003 sensors share one table)."""
        PM = "pmsa003"
        AQI = "air_quality_index"
        BME688 = "bme688"
        SCD41 = "scd41"
        Sound = "sound"
        LTR390 = "ltr390"
        BMP390l = "bmp390l"
        SGP41 = "sgp41"
        ZMOD4510 = "zmod4510"
        ZE07CO = "ze07co"
        AIRTHINGS_RADON = "airthings_radon"

    # Table name -> {column name: SQLite type}. Every table also has a
    # "time" column holding the UTC sample time in milliseconds since the epoch.
    SCHEMA = {
        Point.PM.value: {
            "sensor_index": "INTEGER NOT NULL",
            "pm10_cf1": "INTEGER", "pm25_cf1": "INTEGER", "pm100_cf1": "INTEGER",
            "pm10_std": "INTEGER", "pm25_std": "INTEGER", "pm100_std": "INTEGER",
            "gr03um": "INTEGER", "gr05um": "INTEGER", "gr10um": "INTEGER",
            "gr25um": "INTEGER", "gr50um": "INTEGER", "gr100um": "INTEGER",
        },
        Point.AQI.value: {
            "pm25_cf1_aqi": "REAL",
        },
        Point.Sound.value: {
            "sound_pressure_level": "REAL",
            "la90_raw": "REAL", "baseline": "REAL", "offset": "REAL",
            "offset_saturation_pct": "REAL", "night_reference": "REAL",
            "is_transient": "INTEGER", "in_quiet_hours": "INTEGER", "is_night_anomaly": "INTEGER",
        },
        Point.BME688.value: {
            "temperature": "REAL", "relative_humidity": "REAL", "pressure": "REAL",
            "thom_discomfort_index": "REAL", "gas_resistance": "REAL", "iaq": "REAL",
        },
        Point.SCD41.value: {
            "co2": "INTEGER", "temperature": "REAL", "relative_humidity": "REAL",
        },
        Point.BMP390l.value: {
            "temperature": "REAL", "pressure": "REAL", "altitude": "REAL",
        },
        Point.LTR390.value: {
            "visible_light_lux": "REAL", "uv_index": "REAL",
        },
        Point.SGP41.value: {
            "voc_index": "INTEGER", "nox_index": "INTEGER",
        },
        Point.ZMOD4510.value: {
            "o3_ppb": "REAL", "no2_ppb": "REAL", "fast_aqi": "REAL", "epa_aqi": "REAL",
        },
        Point.ZE07CO.value: {
            "co_ppm": "REAL",
        },
        Point.AIRTHINGS_RADON.value: {
            "radon_1day_avg": "INTEGER", "radon_week_avg": "INTEGER", "radon_year_avg": "INTEGER",
            "temperature": "REAL", "relative_humidity": "REAL",
        },
    }

    DUST_DAILY_COLUMNS = {
        "paired_minutes": "INTEGER", "mean_a": "REAL", "mean_b": "REAL", "ratio": "REAL",
        "correlation": "REAL", "valid_hours": "INTEGER", "flagged_hours": "INTEGER",
    }

    def __init__(self, db_path: Optional[str] = None):
        self._logger = LoggerConfigurator.configure_logger(self.__class__.__name__)
        self._db_path = db_path or os.environ.get("AQ_DB_PATH") or self.DEFAULT_DB_PATH
        self._retention_days = self._read_retention_days()
        self._last_prune: Dict[str, float] = {}
        # Some writers (e.g. the dust sensor) write from several threads.
        # Reentrant, so that writes can be grouped with transaction()
        self._lock = threading.RLock()
        try:
            self._conn = sqlite3.connect(
                self._db_path,
                timeout=self.BUSY_TIMEOUT_SEC,
                isolation_level=None,  # autocommit, each statement is its own transaction
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            # energy of a level in dB, to compute equivalent levels (LAeq) in SQL
            self._conn.create_function("db_to_energy", 1, _db_to_energy, deterministic=True)
            self._conn.execute("PRAGMA journal_mode=WAL")
            # WAL + NORMAL is safe against corruption and reduces SD card writes
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._create_schema()
        except sqlite3.Error as e:
            self._logger.error(f"Cannot open database {self._db_path}: {e}")
            print(f"Error: cannot open database {self._db_path}: {e}", file=sys.stderr)
            sys.exit(1)
        self._logger.info(f"Using SQLite database {self._db_path}")

    def _read_retention_days(self) -> float:
        value = os.environ.get("AQ_DB_RETENTION_DAYS")
        if value is None or value.strip() == "":
            return self.DEFAULT_RETENTION_DAYS
        try:
            return max(0.0, float(value))
        except ValueError:
            self._logger.warning(f"Invalid AQ_DB_RETENTION_DAYS={value!r}, using {self.DEFAULT_RETENTION_DAYS}")
            return self.DEFAULT_RETENTION_DAYS

    def _create_schema(self):
        with self._lock:
            for table, columns in self.SCHEMA.items():
                column_defs = ", ".join(f'"{name}" {sql_type}' for name, sql_type in columns.items())
                self._conn.execute(f'CREATE TABLE IF NOT EXISTS "{table}" ("time" INTEGER NOT NULL, {column_defs})')
                if "sensor_index" in columns:
                    # (time, sensor_index) serves both the time range queries of the
                    # averaging engine and the "latest sample of sensor i" queries
                    self._conn.execute(f'CREATE INDEX IF NOT EXISTS "idx_{table}_time_sensor" ON "{table}" ("time", "sensor_index")')
                    self._conn.execute(f'DROP INDEX IF EXISTS "idx_{table}_sensor_time"')  # former index
                else:
                    self._conn.execute(f'CREATE INDEX IF NOT EXISTS "idx_{table}_time" ON "{table}" ("time")')
            self._conn.execute('CREATE TABLE IF NOT EXISTS "settings" ("key" TEXT PRIMARY KEY, "value" TEXT NOT NULL)')
            # Daily agreement statistics of the two dust sensors (drift detection)
            columns = ", ".join(f'"{name}" {sql_type}' for name, sql_type in self.DUST_DAILY_COLUMNS.items())
            self._conn.execute(f'CREATE TABLE IF NOT EXISTS "dust_sensor_daily" ("day" TEXT PRIMARY KEY, {columns})')
            # User accounts of the web interface (auth.py)
            self._conn.execute('CREATE TABLE IF NOT EXISTS "users" ("username" TEXT PRIMARY KEY, '
                               '"password_hash" TEXT NOT NULL, "created" INTEGER NOT NULL, '
                               '"must_change_password" INTEGER NOT NULL DEFAULT 0)')
            user_columns = {row[1] for row in self._conn.execute('PRAGMA table_info("users")')}
            if "must_change_password" not in user_columns:  # database of a former version
                self._conn.execute('ALTER TABLE "users" ADD COLUMN "must_change_password" INTEGER NOT NULL DEFAULT 0')
            # Daily statistics of every quantity (validation of the sensors with their history)
            self._conn.execute('CREATE TABLE IF NOT EXISTS "sensor_daily" ("day" TEXT NOT NULL, "key" TEXT NOT NULL, '
                               '"mean" REAL, "min_hourly" REAL, "minutes" INTEGER, PRIMARY KEY ("day", "key"))')

    @property
    def db_path(self) -> str:
        return self._db_path

    def close(self):
        with self._lock:
            self._conn.close()

    @contextmanager
    def transaction(self):
        """Groups many writes into one transaction (much faster for bulk imports).
        Only for single-threaded use, the other threads are blocked meanwhile."""
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                yield
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _to_epoch_ms(timestamp) -> int:
        """Converts a sample timestamp to UTC milliseconds since the epoch.

        Accepts datetime objects (including pandas.Timestamp); naive datetimes
        are interpreted as UTC, the same convention the InfluxDB client used.
        Numbers are interpreted as an epoch time in s, ms, us or ns depending
        on their magnitude. None means "now"."""
        if timestamp is None:
            return int(time.time() * 1000)
        if isinstance(timestamp, datetime):
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            return int(timestamp.timestamp() * 1000)
        if isinstance(timestamp, (int, float)):
            magnitude = abs(timestamp)
            if magnitude >= 1e17:
                return int(timestamp // 1_000_000)
            if magnitude >= 1e14:
                return int(timestamp // 1_000)
            if magnitude >= 1e11:
                return int(timestamp)
            return int(timestamp * 1000)
        raise TypeError(f"Unsupported timestamp type: {type(timestamp).__name__}")

    @staticmethod
    def _from_epoch_ms(value: int) -> datetime:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)

    def _write(self, table: str, timestamp, fields: Dict):
        columns = self.SCHEMA[table]
        unknown = set(fields) - set(columns)
        if unknown:
            raise ValueError(f"Unknown field(s) {sorted(unknown)} for table {table}")
        names = ["time"] + list(fields)
        values = [self._to_epoch_ms(timestamp)] + [
            int(v) if isinstance(v, bool) else v for v in fields.values()
        ]
        quoted_names = ", ".join(f'"{name}"' for name in names)
        placeholders = ", ".join("?" * len(names))
        sql = f'INSERT INTO "{table}" ({quoted_names}) VALUES ({placeholders})'
        with self._lock:
            self._conn.execute(sql, values)
        self._prune_if_due(table)

    def _prune_if_due(self, table: str):
        if self._retention_days <= 0:
            return
        now = time.time()
        if now - self._last_prune.get(table, 0) < self.PRUNE_INTERVAL_SEC:
            return
        self._last_prune[table] = now
        cutoff_ms = int((now - self._retention_days * 86400) * 1000)
        try:
            with self._lock:
                deleted = self._conn.execute(f'DELETE FROM "{table}" WHERE "time" < ?', (cutoff_ms,)).rowcount
            if deleted:
                self._logger.info(f"Removed {deleted} sample(s) older than {self._retention_days:g} day(s) from {table}")
        except sqlite3.Error as e:
            self._logger.error(f"Cannot prune table {table}: {e}")

    def _read(self, table: str, where: str = "", params: tuple = ()) -> Optional[Dict]:
        """Returns the most recent sample of the table (not older than
        MAX_SAMPLE_AGE_SEC) as a dict with a timezone aware UTC "time" key,
        or None if there is no recent sample."""
        min_time_ms = int((time.time() - self.MAX_SAMPLE_AGE_SEC) * 1000)
        sql = f'SELECT * FROM "{table}" WHERE "time" > ?'
        if where:
            sql += f" AND ({where})"
        sql += ' ORDER BY "time" DESC LIMIT 1'
        try:
            with self._lock:
                row = self._conn.execute(sql, (min_time_ms, *params)).fetchone()
        except sqlite3.Error as e:
            self._logger.error(f"Cannot read from {table}: {e}")
            return None
        if row is None:
            return None
        record = dict(row)
        record["time"] = self._from_epoch_ms(record["time"])
        return record

    def read_minute_aggregates(self, table: str, columns: Iterable[str], start_ms: int, end_ms: int
                               ) -> List[Tuple[int, Dict]]:
        """Per minute sums and counts of the given columns for start_ms <= time <= end_ms.
        Returns [(minute, {column: (sum, count)})] where minute = time // 60000.
        For the tables of several sensors (sensor_index column) the values of
        each sensor are also returned, with the keys (column, sensor index)."""
        columns = list(columns)
        expressions = [column_expression(c) for c in columns]
        unknown = {column for column, _ in expressions} - set(self.SCHEMA[table])
        if unknown:
            raise ValueError(f"Unknown column(s) {sorted(unknown)} for table {table}")
        per_sensor = "sensor_index" in self.SCHEMA[table]
        aggregates = ", ".join(f'SUM({expression}), COUNT("{column}")' for column, expression in expressions)
        sensor = '"sensor_index"' if per_sensor else "NULL"
        group = "minute, \"sensor_index\"" if per_sensor else "minute"
        sql = (f'SELECT "time" / 60000 AS minute, {sensor}, {aggregates} FROM "{table}" '
               f'WHERE "time" >= ? AND "time" <= ? GROUP BY {group} ORDER BY minute')
        try:
            with self._lock:
                rows = self._conn.execute(sql, (int(start_ms), int(end_ms))).fetchall()
        except sqlite3.Error as e:
            self._logger.error(f"Cannot aggregate {table}: {e}")
            return []
        result: Dict[int, Dict] = {}
        for row in rows:
            values = result.setdefault(int(row[0]), {})
            for i, column in enumerate(columns):
                total, count = row[2 + 2 * i], row[3 + 2 * i]
                if not count:
                    continue
                if per_sensor:
                    values[(column, int(row[1]))] = (float(total), int(count))
                previous_total, previous_count = values.get(column, (0.0, 0))
                values[column] = (previous_total + float(total), previous_count + int(count))
        return sorted(result.items())

    def read_sensor_minute_means(self, table: str, column: str, start_ms: int, end_ms: int) -> Dict[int, Dict[int, float]]:
        """{minute: {sensor index: mean}} for a table of several sensors."""
        means: Dict[int, Dict[int, float]] = {}
        for minute, values in self.read_minute_aggregates(table, [column], start_ms, end_ms):
            for key, (total, count) in values.items():
                if isinstance(key, tuple):
                    means.setdefault(minute, {})[key[1]] = total / count
        return means

    def read_minute_statistics(self, table: str, columns: List[str], start_ms: int, end_ms: int,
                               valid_ranges: Dict[str, Tuple[float, float]]):
        """Per minute (mean, min, max, count) of each column, and per column the
        number of readings and of readings outside its valid range."""
        unknown = set(columns) - set(self.SCHEMA[table])
        if unknown:
            raise ValueError(f"Unknown column(s) {sorted(unknown)} for table {table}")
        parts = ", ".join(f'AVG("{c}"), MIN("{c}"), MAX("{c}"), COUNT("{c}")' for c in columns)
        outside = ", ".join(f'COUNT("{c}"), SUM(CASE WHEN "{c}" < ? OR "{c}" > ? THEN 1 ELSE 0 END)' for c in columns)
        range_params = [v for c in columns for v in valid_ranges.get(c, (float("-inf"), float("inf")))]
        stats: Dict[str, Dict[int, Tuple]] = {c: {} for c in columns}
        totals: Dict[str, Tuple[int, int]] = {}
        try:
            with self._lock:
                rows = self._conn.execute(f'SELECT "time" / 60000 AS minute, {parts} FROM "{table}" WHERE "time" >= ? '
                                          f'AND "time" <= ? GROUP BY minute', (int(start_ms), int(end_ms))).fetchall()
                total_row = self._conn.execute(f'SELECT {outside} FROM "{table}" WHERE "time" >= ? AND "time" <= ?',
                                               (*range_params, int(start_ms), int(end_ms))).fetchone()
        except sqlite3.Error as e:
            self._logger.error(f"Cannot read the statistics of {table}: {e}")
            return stats, totals
        for row in rows:
            for i, column in enumerate(columns):
                mean, low, high, count = row[1 + 4 * i: 5 + 4 * i]
                if count:
                    stats[column][int(row[0])] = (float(mean), float(low), float(high), int(count))
        for i, column in enumerate(columns):
            totals[column] = (int(total_row[2 * i] or 0), int(total_row[2 * i + 1] or 0))
        return stats, totals

    def write_sensor_daily(self, day: str, statistics_by_key: Dict[str, Dict]):
        """Stores the daily statistics; a marker row records days without data."""
        rows = [(day, key, v["mean"], v["min_hourly"], v["minutes"]) for key, v in statistics_by_key.items()]
        rows.append((day, "_day", None, None, 0))
        with self._lock:
            self._conn.executemany('INSERT OR REPLACE INTO "sensor_daily" ("day", "key", "mean", "min_hourly", "minutes") '
                                   'VALUES (?, ?, ?, ?, ?)', rows)

    def read_sensor_daily_days(self, since_day: str = "") -> List[str]:
        with self._lock:
            return [r[0] for r in self._conn.execute('SELECT DISTINCT "day" FROM "sensor_daily" WHERE "day" >= ?', (since_day,))]

    def read_sensor_daily(self, since_day: str = "") -> List[Tuple[str, Dict[str, Dict]]]:
        """[(day, {key: {mean, min_hourly, minutes}})] ordered by day."""
        with self._lock:
            rows = self._conn.execute('SELECT * FROM "sensor_daily" WHERE "day" >= ? AND "key" != \'_day\' '
                                      'ORDER BY "day"', (since_day,)).fetchall()
        days: Dict[str, Dict[str, Dict]] = {}
        for row in rows:
            days.setdefault(row["day"], {})[row["key"]] = {"mean": row["mean"], "min_hourly": row["min_hourly"],
                                                           "minutes": row["minutes"]}
        return sorted(days.items())

    # ------------------------------------------------------------ users

    def list_users(self) -> List[str]:
        with self._lock:
            return [r[0] for r in self._conn.execute('SELECT "username" FROM "users" ORDER BY "username"')]

    def get_user(self, username: str) -> Optional[Dict]:
        with self._lock:
            row = self._conn.execute('SELECT * FROM "users" WHERE "username" = ?', (username,)).fetchone()
        return dict(row) if row else None

    def write_user(self, username: str, password_hash: str, must_change_password: bool = False):
        with self._lock:
            self._conn.execute('INSERT INTO "users" ("username", "password_hash", "created", "must_change_password") '
                               'VALUES (?, ?, ?, ?) ON CONFLICT("username") DO UPDATE SET '
                               '"password_hash" = excluded."password_hash", '
                               '"must_change_password" = excluded."must_change_password"',
                               (username, password_hash, int(time.time()), int(bool(must_change_password))))

    def delete_user(self, username: str):
        with self._lock:
            self._conn.execute('DELETE FROM "users" WHERE "username" = ?', (username,))

    def write_dust_daily(self, day: str, record: Dict):
        names = ["day"] + list(self.DUST_DAILY_COLUMNS)
        values = [day] + [record.get(name) for name in self.DUST_DAILY_COLUMNS]
        quoted = ", ".join(f'"{n}"' for n in names)
        with self._lock:
            self._conn.execute(f'INSERT OR REPLACE INTO "dust_sensor_daily" ({quoted}) '
                               f'VALUES ({", ".join("?" * len(names))})', values)

    def read_dust_daily(self, since_day: str = "") -> List[Dict]:
        with self._lock:
            rows = self._conn.execute('SELECT * FROM "dust_sensor_daily" WHERE "day" >= ? ORDER BY "day"',
                                      (since_day,)).fetchall()
        return [dict(row) for row in rows]

    def first_sample_time(self, table: str) -> Optional[datetime]:
        with self._lock:
            value = self._conn.execute(f'SELECT MIN("time") FROM "{table}"').fetchone()[0]
        return None if value is None else self._from_epoch_ms(value)

    # ------------------------------------------------------------------ settings

    def read_settings(self) -> Dict:
        """Returns the stored settings (JSON values) as a dict."""
        try:
            with self._lock:
                rows = self._conn.execute('SELECT "key", "value" FROM "settings"').fetchall()
        except sqlite3.Error as e:
            self._logger.error(f"Cannot read settings: {e}")
            return {}
        settings = {}
        for row in rows:
            try:
                settings[row["key"]] = json.loads(row["value"])
            except ValueError:
                self._logger.warning(f"Ignoring invalid setting {row['key']!r}")
        return settings

    def write_settings(self, settings: Dict):
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                for key, value in settings.items():
                    self._conn.execute('INSERT INTO "settings" ("key", "value") VALUES (?, ?) '
                                       'ON CONFLICT("key") DO UPDATE SET "value" = excluded."value"',
                                       (key, json.dumps(value)))
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    # ------------------------------------------------------------------ writers

    def write_pm(self, i, sample):
        self._write(self.Point.PM.value, sample.timestamp, {
            "sensor_index": i,
            "pm10_cf1": sample.pm10_cf1,
            "pm25_cf1": sample.pm25_cf1,
            "pm100_cf1": sample.pm100_cf1,
            "pm10_std": sample.pm10_std,
            "pm25_std": sample.pm25_std,
            "pm100_std": sample.pm100_std,
            "gr03um": sample.gr03um,
            "gr05um": sample.gr05um,
            "gr10um": sample.gr10um,
            "gr25um": sample.gr25um,
            "gr50um": sample.gr50um,
            "gr100um": sample.gr100um,
        })

    def write_aqi(self, timestamp, pm25_cf1_aqi):
        self._write(self.Point.AQI.value, timestamp, {"pm25_cf1_aqi": pm25_cf1_aqi})

    def write_sound_pressure_level(self, timestamp, spl, diagnostics: Dict = None):
        """Write the calibrated sound pressure level, plus optional diagnostic
        fields from NoiseDetector (la90_raw, baseline, offset,
        offset_saturation_pct, is_transient, in_quiet_hours, night_reference,
        is_night_anomaly) so that nighttime anomalies and calibration health
        can be audited after the fact instead of only seeing the final
        calibrated number."""
        fields = {"sound_pressure_level": spl}
        if diagnostics:
            for key in ("la90_raw", "baseline", "offset", "offset_saturation_pct", "night_reference"):
                value = diagnostics.get(key)
                if value is not None:
                    fields[key] = float(value)
            for key in ("is_transient", "in_quiet_hours", "is_night_anomaly"):
                value = diagnostics.get(key)
                if value is not None:
                    fields[key] = bool(value)
        self._write(self.Point.Sound.value, timestamp, fields)

    def write_ambient_data(self, timestamp, temperature, gas, relative_humidity, pressure, iaq, thom_discomfort_index=None):
        self._write(self.Point.BME688.value, timestamp, {
            "temperature": temperature,
            "relative_humidity": relative_humidity,
            "pressure": pressure,
            "thom_discomfort_index": thom_discomfort_index,
            "gas_resistance": gas,
            "iaq": iaq,
        })

    def write_light_data(self, timestamp, visible_light_lux, uv_index):
        self._write(self.Point.LTR390.value, timestamp, {
            "visible_light_lux": visible_light_lux,
            "uv_index": uv_index,
        })

    def write_co2_data(self, timestamp, co2, temperature, relative_humidity):
        self._write(self.Point.SCD41.value, timestamp, {
            "co2": co2,
            "temperature": temperature,
            "relative_humidity": relative_humidity,
        })

    def write_bmp390l_data(self, timestamp, temperature, pressure, altitude):
        self._write(self.Point.BMP390l.value, timestamp, {
            "temperature": temperature,
            "pressure": pressure,
            "altitude": altitude,
        })

    def write_sgp41_data(self, timestamp, voc_index, nox_index):
        self._write(self.Point.SGP41.value, timestamp, {
            "voc_index": voc_index,
            "nox_index": nox_index,
        })

    def write_radon_data(self, timestamp, radon_1day_avg, radon_week_avg, radon_year_avg, temperature, relative_humidity):
        values = (radon_1day_avg, radon_week_avg, radon_year_avg, temperature, relative_humidity)
        if all(v is None for v in values):
            return
        self._write(self.Point.AIRTHINGS_RADON.value, timestamp, {
            "radon_1day_avg": radon_1day_avg,
            "radon_week_avg": radon_week_avg,
            "radon_year_avg": radon_year_avg,
            "temperature": temperature,
            "relative_humidity": relative_humidity,
        })

    def write_zmod4510_data(self, timestamp, o3_ppb, no2_ppb, fast_aqi, epa_aqi):
        self._write(self.Point.ZMOD4510.value, timestamp, {
            "o3_ppb": o3_ppb,
            "no2_ppb": no2_ppb,
            "fast_aqi": fast_aqi,
            "epa_aqi": epa_aqi,
        })

    def write_co_data(self, timestamp, co_ppm):
        self._write(self.Point.ZE07CO.value, timestamp, {"co_ppm": co_ppm})

    # ------------------------------------------------------------------ readers

    def read_pm(self, i: int):
        return self._read(self.Point.PM.value, '"sensor_index" = ?', (i,))

    def read_aqi(self):
        return self._read(self.Point.AQI.value)

    def read_sound_pressure_level(self):
        return self._read(self.Point.Sound.value)

    def read_ambient_data(self):
        return self._read(self.Point.BME688.value)

    def read_temperature_relative_humidity_data(self):
        d = self._read(self.Point.BME688.value)
        if d is not None:
            return d["temperature"], d["relative_humidity"]
        return None, None

    def read_light_data(self):
        return self._read(self.Point.LTR390.value)

    def read_co2_data(self):
        return self._read(self.Point.SCD41.value)

    def read_sgp41_data(self):
        return self._read(self.Point.SGP41.value)

    def read_radon_data(self):
        # Rows may only carry temperature/humidity; the dashboard needs radon values
        return self._read(
            self.Point.AIRTHINGS_RADON.value,
            '"radon_1day_avg" IS NOT NULL OR "radon_week_avg" IS NOT NULL OR "radon_year_avg" IS NOT NULL',
        )

    def read_zmod4510_data(self):
        return self._read(self.Point.ZMOD4510.value)

    def read_co_data(self):
        return self._read(self.Point.ZE07CO.value)

#!/usr/bin/env python3
#
# sudo systemctl status influxdb3-core
# journalctl -u influxdb3-core
# influxdb3 show databases
# curl "http://localhost:8181/health" --header "Authorization: Bearer $INFLUXDB3_ADMIN_TOKEN"

try:
    from influxdb_client_3 import InfluxDBClient3, WritePrecision, Point
except ModuleNotFoundError:  # test-only SQLite mode does not need the client
    InfluxDBClient3 = WritePrecision = Point = None
from typing import Dict
from logger_configurator import LoggerConfigurator
from enum import Enum
import os, sys


class _InfluxStorage:
    auth_scheme = "Bearer"
    host = "http://localhost:8181"

    class Database(Enum):
        Dust = "dust"
        Gas = "gas"
        Climate = "climate"
        Sound = "sound"
        Light = "light"

    class Point(Enum):
        PM = "pmsa003_"
        AQI = "air_quality_index"
        BME688 = "bme688"
        SCD41 = "scd41"
        Sound = "sound"
        LTR390 = "ltr390"
        BMP390l = "bmp390l"
        SGP41 = "sgp41"
        ZMOD4510 = "zmod4510"
        ZE07CO = "ze07co"
        AIRTHINGS_RADON = "airthings_radon"

    def __init__(self, db_path=None):
        self._logger = LoggerConfigurator.configure_logger(self.__class__.__name__)
        self._token = os.environ.get("INFLUXDB3_AUTH_TOKEN")
        if not self._token:
            raise RuntimeError("INFLUXDB3_AUTH_TOKEN environment variable is not set.")

        self._clients: Dict[str, InfluxDBClient3] = {}
        self._verify_token()

    def get_client(self, database: str) -> InfluxDBClient3:
        """Get or create a client for specific database"""
        if database not in self._clients:
            self._clients[database] = InfluxDBClient3(
                host=self.host,
                token=self._token,
                database=database,
                auth_scheme=self.auth_scheme
            )
        return self._clients[database]

    def _verify_token(self):
        try:
            client = self.get_client(self.Database.Dust.value)
            client.query("SELECT 1")
            self._logger.info("Token verification successful.")
        except Exception as e:
            if "unauthorized" in str(e).lower() or "authentication" in str(e).lower():
                self._logger.error(f"Token verification failed: {e}")
            else:
                self._logger.error(f"An unexpected error occurred during token verification: {e}")
            sys.exit(1)

    def _write(self, db: Database, point: Point):
        client = self.get_client(db.value)
        client.write(record=point, write_precision=WritePrecision.MS)

    def write_pm(self, i, sample):
        point = (
            Point(f"{self.Point.PM.value}{i}")
            .time(sample.timestamp)
            .field("pm10_cf1", sample.pm10_cf1)
            .field("pm25_cf1", sample.pm25_cf1)
            .field("pm100_cf1", sample.pm100_cf1)
            .field("pm10_std", sample.pm10_std)
            .field("pm25_std", sample.pm25_std)
            .field("pm100_std", sample.pm100_std)
            .field("gr03um", sample.gr03um)
            .field("gr05um", sample.gr05um)
            .field("gr10um", sample.gr10um)
            .field("gr25um", sample.gr25um)
            .field("gr50um", sample.gr50um)
            .field("gr100um", sample.gr100um)
        )
        self._write(self.Database.Dust, point)

    def write_aqi(self, timestamp, pm25_cf1_aqi):
        point = (
            Point(self.Point.AQI.value)
            .time(timestamp)
            .field("pm25_cf1_aqi", pm25_cf1_aqi)
        )
        self._write(self.Database.Dust, point)

    def write_sound_pressure_level(self, timestamp, spl, diagnostics: Dict = None):
        """Write the calibrated sound pressure level, plus optional diagnostic
        fields from NoiseDetector (la90_raw, baseline, offset,
        offset_saturation_pct, is_transient, in_quiet_hours, night_reference,
        is_night_anomaly) so that nighttime anomalies and calibration health
        can be audited after the fact instead of only seeing the final
        calibrated number."""
        point = (
            Point(self.Point.Sound.value)
            .time(timestamp)
            .field("sound_pressure_level", spl)
        )
        if diagnostics:
            for key in ("la90_raw", "baseline", "offset", "offset_saturation_pct", "night_reference"):
                value = diagnostics.get(key)
                if value is not None:
                    point = point.field(key, float(value))
            for key in ("is_transient", "in_quiet_hours", "is_night_anomaly"):
                value = diagnostics.get(key)
                if value is not None:
                    point = point.field(key, bool(value))
        self._write(self.Database.Sound, point)

    def write_ambient_data(self, timestamp, temperature, gas, relative_humidity, pressure, iaq, thom_discomfort_index=None):
        point = (
            Point(self.Point.BME688.value)
            .time(timestamp)
            .field("gas_resistance", gas)
            .field("iaq", iaq)
        )
        self._write(self.Database.Gas, point)
        point = (
            Point(self.Point.BME688.value)
            .time(timestamp)
            .field("temperature", temperature)
            .field("relative_humidity", relative_humidity)
            .field("pressure", pressure)
        )
        if thom_discomfort_index is not None:
            point = point.field("thom_discomfort_index", thom_discomfort_index)
        self._write(self.Database.Climate, point)

    def write_light_data(self, timestamp, visible_light_lux, uv_index):
        point = (
            Point(self.Point.LTR390.value)
            .time(timestamp)
            .field("visible_light_lux", visible_light_lux)
            .field("uv_index", uv_index)
        )
        self._write(self.Database.Light, point)

    def write_co2_data(self, timestamp, co2, temperature, relative_humidity):
        point = (
            Point(self.Point.SCD41.value)
            .time(timestamp)
            .field("co2", co2)
        )
        self._write(self.Database.Gas, point)
        point = (
            Point(self.Point.SCD41.value)
            .time(timestamp)
            .field("temperature", temperature)
            .field("relative_humidity", relative_humidity)
        )
        self._write(self.Database.Climate, point)

    def write_bmp390l_data(self, timestamp, temperature, pressure, altitude):
        point = (
            Point(self.Point.BMP390l.value)
            .time(timestamp)
            .field("temperature", temperature)
            .field("pressure", pressure)
            .field("altitude", altitude)
        )
        self._write(self.Database.Climate, point)

    def write_sgp41_data(self, timestamp, voc_index, nox_index):
        point = (
            Point(self.Point.SGP41.value)
            .time(timestamp)
            .field("voc_index", voc_index)
            .field("nox_index", nox_index)
        )
        self._write(self.Database.Gas, point)

    def write_radon_data(self, timestamp, radon_1day_avg, radon_week_avg, radon_year_avg, temperature, relative_humidity):
        if radon_1day_avg is not None or radon_week_avg is not None or radon_year_avg is not None:
            point = (
                Point(self.Point.AIRTHINGS_RADON.value)
                .time(timestamp)
                .field("radon_1day_avg", radon_1day_avg)
                .field("radon_week_avg", radon_week_avg)
                .field("radon_year_avg", radon_year_avg)
            )
            self._write(self.Database.Gas, point)
        if temperature is not None or relative_humidity is not None:
            point = (
                Point(self.Point.AIRTHINGS_RADON.value)
                .time(timestamp)
                .field("temperature", temperature)
                .field("relative_humidity", relative_humidity)
            )
            self._write(self.Database.Climate, point)

    def write_zmod4510_data(self, timestamp, o3_ppb, no2_ppb, fast_aqi, epa_aqi):
        point = (
            Point(self.Point.ZMOD4510.value)
            .time(timestamp)
            .field("o3_ppb", o3_ppb)
            .field("no2_ppb", no2_ppb)
            .field("fast_aqi", fast_aqi)
            .field("epa_aqi", epa_aqi)
        )
        self._write(self.Database.Gas, point)

    def write_co_data(self, timestamp, co_ppm):
        point = (
            Point(self.Point.ZE07CO.value)
            .time(timestamp)
            .field("co_ppm", co_ppm)
        )
        self._write(self.Database.Gas, point)

    def _read(self, db: Database, point_name):
        try:
            client = self.get_client(db.value)
            df = client.query(
                        query=f'SELECT * FROM "{point_name}" WHERE time > now() - interval \'10 minutes\' ORDER BY time DESC LIMIT 1',
                        language="sql",
                        mode="pandas"
                    )
            records = df.to_dict(orient="records")
            return records[-1] if records else None
        except Exception:
            pass
            # self._logger.error(f"Cannot read from {point_name}")
        return None

    @staticmethod
    def _merge(left, right):
        if left is None and right is None:
            return None
        if left is None:
            return right
        if right is None:
            return left
        merged = left.copy()
        merged.update(right)
        return merged

    def read_pm(self, i: int):
        return self._read(self.Database.Dust, f'{self.Point.PM.value}{i}')

    def read_aqi(self):
        return self._read(self.Database.Dust, self.Point.AQI.value)

    def read_sound_pressure_level(self):
        return self._read(self.Database.Sound, self.Point.Sound.value)

    def read_ambient_data(self):
        gas = self._read(self.Database.Gas, self.Point.BME688.value)
        climate = self._read(self.Database.Climate, self.Point.BME688.value)
        return PersistentStorage._merge(gas, climate)

    def read_temperature_relative_humidity_data(self):
        d = self._read(self.Database.Climate, self.Point.BME688.value)
        if d is not None:
            return d["temperature"], d["relative_humidity"]
        return None, None

    def read_light_data(self):
        return self._read(self.Database.Light, self.Point.LTR390.value)

    def read_co2_data(self):
        gas = self._read(self.Database.Gas, self.Point.SCD41.value)
        climate = self._read(self.Database.Climate, self.Point.SCD41.value)
        return PersistentStorage._merge(gas, climate)

    def read_sgp41_data(self):
        return self._read(self.Database.Gas, self.Point.SGP41.value)
    
    def read_radon_data(self):
        radon = self._read(self.Database.Gas, self.Point.AIRTHINGS_RADON.value)
        if radon is not None:
            print(radon)
            return radon
        print("Radon data not found")
        return None

    def read_zmod4510_data(self):
        return self._read(self.Database.Gas, self.Point.ZMOD4510.value)
    
    def read_co_data(self):
        return self._read(self.Database.Gas, self.Point.ZE07CO.value)



class PersistentStorage:
    """Use InfluxDB for production sensor data and the isolated SQLite implementation for tests.

    A path argument is intentionally test-only: the application constructs this class
    without a path, so its sensor data remains in the existing InfluxDB databases.
    The SQLite metadata store mirrors writes needed by the new history/health APIs;
    it is a local cache and never replaces the InfluxDB sensor databases.
    """

    _META_METHODS = {
        "read_minute_aggregates", "read_sensor_minute_means", "read_minute_statistics",
        "write_sensor_daily", "read_sensor_daily_days", "read_sensor_daily",
        "list_users", "get_user", "write_user", "delete_user",
        "write_dust_daily", "read_dust_daily", "first_sample_time",
        "read_settings", "write_settings",
    }
    _WRITE_METHODS = {
        "write_pm", "write_aqi", "write_sound_pressure_level", "write_ambient_data",
        "write_light_data", "write_co2_data", "write_bmp390l_data", "write_sgp41_data",
        "write_radon_data", "write_zmod4510_data", "write_co_data",
    }

    def __init__(self, db_path=None):
        if db_path is not None:
            self._impl = _SQLiteStorage(db_path)
            self._meta = None
        else:
            if InfluxDBClient3 is None:
                raise RuntimeError("influxdb3-python is required for production storage")
            self._impl = _InfluxStorage()
            meta_path = os.environ.get(
                "AQ_METADATA_DB_PATH",
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "aq_dashboard_metadata.db"),
            )
            self._meta = _SQLiteStorage(meta_path)

    def __getattr__(self, name):
        if name in self._META_METHODS:
            return getattr(self._impl if self._meta is None else self._meta, name)
        if name in self._WRITE_METHODS and self._meta is not None:
            influx_method = getattr(self._impl, name)
            meta_method = getattr(self._meta, name)
            def mirrored(*args, **kwargs):
                result = influx_method(*args, **kwargs)
                meta_method(*args, **kwargs)
                return result
            return mirrored
        return getattr(self._impl, name)

    def close(self):
        self._impl.close() if hasattr(self._impl, "close") else None
        self._meta.close() if self._meta is not None else None

    @property
    def db_path(self):
        if self._meta is not None:
            return self._meta.db_path
        return None
