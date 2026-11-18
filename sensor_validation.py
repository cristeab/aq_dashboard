#!/usr/bin/env python3
"""
Validation of the measurements of all sensors with their historical data.

Checks of each quantity over the last 24 hours:
- range: readings outside the measurement range of the sensor or physically
  impossible (e.g. relative humidity above 100 %);
- jumps: changes between consecutive minutes that are physically implausible
  for slowly varying quantities (e.g. indoor temperature);
- stuck: a quantity that always fluctuates (sensor noise) reports exactly the
  same value for hours, e.g. a frozen driver;
- gaps: less than 80 % of the minutes have data.

Checks with the daily statistics of the last weeks (table sensor_daily):
- drift between sensors measuring the same quantity (temperature: BME688,
  SCD41, BMP390, Airthings; humidity: BME688, SCD41, Airthings; pressure:
  BME688, BMP390). For each sensor, the difference between its daily mean and
  the median of the other sensors is compared with the difference of its first
  days (baseline), so that constant offsets (self-heating, placement) are
  allowed. With three sensors or more, the drifting sensor is identified.
- CO2 baseline: the automatic self-calibration of the SCD41 assumes that the
  room gets fresh air at least once a week, so the lowest hourly mean of the
  last 7 days should be close to the outdoor level (about 420 ppm). Lower
  values are impossible (calibration error), higher values mean that the room
  is never ventilated well or that the sensor reads too high.

The dust sensors are checked by dust_sensor_monitor.py; its alarms are part of
the report.
"""

import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

DAY_MS = 86400000


@dataclass(frozen=True)
class Quantity:
    sensor: str
    name: str                   # quantity id, e.g. "temperature"
    table: str
    column: str
    unit: str
    valid_range: Tuple[float, float]
    max_rate: Optional[float] = None       # maximal plausible change per minute
    stuck_hours: Optional[float] = None    # hours without any change -> stuck
    compare: Optional[str] = None          # group of sensors measuring the same quantity


QUANTITIES = [
    Quantity("bme688", "temperature", "bme688", "temperature", "°C", (-40, 85), 2.0, 6, "temperature"),
    Quantity("bme688", "relative_humidity", "bme688", "relative_humidity", "%", (0, 100), 10.0, 6, "humidity"),
    Quantity("bme688", "pressure", "bme688", "pressure", "hPa", (300, 1100), 2.0, 12, "pressure"),
    Quantity("bme688", "gas_resistance", "bme688", "gas_resistance", "Ω", (1, 1e9)),
    Quantity("scd41", "co2", "scd41", "co2", "ppm", (300, 40000), 1500.0, 6),
    Quantity("scd41", "temperature", "scd41", "temperature", "°C", (-10, 60), 2.0, 6, "temperature"),
    Quantity("scd41", "relative_humidity", "scd41", "relative_humidity", "%", (0, 100), 10.0, 6, "humidity"),
    Quantity("bmp390l", "temperature", "bmp390l", "temperature", "°C", (-40, 85), 2.0, 6, "temperature"),
    Quantity("bmp390l", "pressure", "bmp390l", "pressure", "hPa", (300, 1250), 2.0, 12, "pressure"),
    Quantity("sgp41", "voc_index", "sgp41", "voc_index", "", (1, 500)),
    Quantity("sgp41", "nox_index", "sgp41", "nox_index", "", (1, 500)),
    Quantity("zmod4510", "o3", "zmod4510", "o3_ppb", "ppb", (0, 1000)),
    Quantity("zmod4510", "no2", "zmod4510", "no2_ppb", "ppb", (0, 1000)),
    Quantity("ze07co", "co", "ze07co", "co_ppm", "ppm", (0, 500)),
    Quantity("ltr390", "visible_light", "ltr390", "visible_light_lux", "lux", (0, 160000)),
    Quantity("ltr390", "uv_index", "ltr390", "uv_index", "", (0, 20)),
    Quantity("sound", "noise", "sound", "sound_pressure_level", "dB", (0, 140), None, 3),
    Quantity("airthings", "radon", "airthings_radon", "radon_1day_avg", "Bq/m³", (0, 20000)),
    Quantity("airthings", "temperature", "airthings_radon", "temperature", "°C", (-10, 60), None, None, "temperature"),
    Quantity("airthings", "relative_humidity", "airthings_radon", "relative_humidity", "%", (0, 100), None, None, "humidity"),
]
SENSORS = ["bme688", "scd41", "bmp390l", "sgp41", "zmod4510", "ze07co", "ltr390", "sound", "airthings", "pmsa003"]
DRIFT_THRESHOLDS = {"temperature": 2.0, "humidity": 8.0, "pressure": 2.0}   # °C, %RH, hPa

# English texts of the issues (for the log; the web interface translates them)
MESSAGES = {
    "out_of_range": "{sensor} {quantity}: {count} readings of the last 24 h are outside the valid range ({low} to {high} {unit}).",
    "jumps": "{sensor} {quantity}: {count} implausible jumps in the last 24 h.",
    "stuck": "{sensor} {quantity}: the same value ({value} {unit}) for {hours} hours.",
    "gaps": "{sensor}: data for only {percent} % of the last 24 h.",
    "drift": "{sensor} {quantity} has drifted by {drift} {unit} compared with the other sensors.",
    "drift_pair": "The {quantity} of {sensor} and {other} has drifted apart by {drift} {unit}.",
    "co2_baseline_low": "{sensor}: the lowest CO2 level of the last 7 days ({value} ppm) is below the outdoor level.",
    "co2_baseline_high": "{sensor}: the CO2 level has not come down to the outdoor level for 7 days (lowest {value} ppm).",
}


def issue_message(issue: Dict) -> str:
    return MESSAGES[issue["code"]].format(**issue["params"])


class SensorValidator:
    EVALUATION_INTERVAL_SEC = 600
    WINDOW_HOURS = 24
    OUT_OF_RANGE_ALARM = 0.05        # fraction of the readings
    MIN_JUMPS = 3
    MIN_COMPLETENESS = 0.80
    HISTORY_DAYS = 30
    BASELINE_DAYS = 5
    RECENT_DAYS = 3
    MIN_DAY_MINUTES = 12 * 60
    CO2_BASELINE_DAYS = 7
    CO2_BASELINE_LOW = 370           # ppm, impossible indoors
    CO2_BASELINE_HIGH = 550          # ppm
    SETTING_BASELINE_START = "sensor_baseline_start"

    def __init__(self, storage, logger, clock=time.time):
        self._storage = storage
        self._logger = logger
        self._clock = clock
        self._last_evaluation = 0.0
        self.report: Dict = {"sensors": [], "evaluated": None}
        self.alarms: List[Dict] = []

    # ------------------------------------------------------------ statistics

    def _minute_stats(self, table: str, columns: List[str], start_ms: int, end_ms: int):
        """{column: {minute: (mean, min, max, count)}} and {column: (readings, out of range)}."""
        return self._storage.read_minute_statistics(table, columns, start_ms, end_ms,
                                                    {q.column: q.valid_range for q in QUANTITIES if q.table == table})

    def _check_quantity(self, quantity: Quantity, minutes: Dict[int, Tuple], totals: Tuple[int, int],
                        now_minute: int) -> List[Dict]:
        issues = []
        base = {"sensor": quantity.sensor, "quantity": quantity.name, "unit": quantity.unit}
        readings, outside = totals
        if outside:
            issues.append({"code": "out_of_range", "severity": "alarm" if outside >= self.OUT_OF_RANGE_ALARM * readings else "warning",
                           "params": {**base, "count": outside, "low": quantity.valid_range[0], "high": quantity.valid_range[1]}})
        if quantity.max_rate is not None:
            jumps = sum(1 for m in minutes if m - 1 in minutes and abs(minutes[m][0] - minutes[m - 1][0]) > quantity.max_rate)
            if jumps >= self.MIN_JUMPS:
                issues.append({"code": "jumps", "severity": "warning", "params": {**base, "count": jumps}})
        if quantity.stuck_hours is not None:
            window = [minutes[m] for m in range(now_minute - int(quantity.stuck_hours * 60) + 1, now_minute + 1) if m in minutes]
            if len(window) >= 0.75 * quantity.stuck_hours * 60:
                low, high = min(w[1] for w in window), max(w[2] for w in window)
                if high - low == 0:
                    issues.append({"code": "stuck", "severity": "alarm",
                                   "params": {**base, "value": low, "hours": quantity.stuck_hours}})
        return issues

    def read_day(self, day_start_ms: int) -> Dict[str, Dict]:
        """Daily statistics of every quantity: mean, lowest hourly mean, minutes with data."""
        result = {}
        for table in sorted({q.table for q in QUANTITIES}):
            quantities = [q for q in QUANTITIES if q.table == table]
            stats, _ = self._minute_stats(table, [q.column for q in quantities], day_start_ms, day_start_ms + DAY_MS - 1)
            for q in quantities:
                minutes = stats.get(q.column, {})
                if not minutes:
                    continue
                hours: Dict[int, List[float]] = {}
                for minute, (mean, _, _, _) in minutes.items():
                    hours.setdefault(minute // 60, []).append(mean)
                hourly = [statistics.fmean(v) for v in hours.values() if len(v) >= 45]
                result[f"{q.sensor}.{q.name}"] = {
                    "mean": statistics.fmean(m[0] for m in minutes.values()),
                    "min_hourly": min(hourly) if hourly else None,
                    "minutes": len(minutes),
                }
        return result

    def _summarize_missing_day(self, now: float) -> bool:
        today_start = int(now * 1000) // DAY_MS * DAY_MS
        first = min((t for t in (self._storage.first_sample_time(table) for table in {q.table for q in QUANTITIES}) if t),
                    default=None)
        if first is None:
            return False
        start = max(int(first.timestamp() * 1000) // DAY_MS * DAY_MS, today_start - self.HISTORY_DAYS * DAY_MS)
        known = set(self._storage.read_sensor_daily_days(self._day(start)))
        for day_start in range(start, today_start, DAY_MS):
            day = self._day(day_start)
            if day not in known:
                self._storage.write_sensor_daily(day, self.read_day(day_start))
                return True
        return False

    @staticmethod
    def _day(ms: int) -> str:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")

    # ------------------------------------------------------------ evaluation

    def reset_baseline(self):
        """After replacing or recalibrating a sensor: new baseline of the drift checks from tomorrow."""
        tomorrow = self._day((int(self._clock() * 1000) // DAY_MS + 1) * DAY_MS)
        self._storage.write_settings({self.SETTING_BASELINE_START: tomorrow})
        self._last_evaluation = 0.0

    def evaluate(self, dust_alarms: Optional[List[Dict]] = None, force: bool = False) -> bool:
        now = self._clock()
        backlog = self._summarize_missing_day(now)
        if not force and not backlog and now - self._last_evaluation < self.EVALUATION_INTERVAL_SEC:
            if dust_alarms is not None:
                self._set_dust(dust_alarms)
            return False
        self._last_evaluation = now
        now_ms = int(now * 1000)
        now_minute = now_ms // 60000
        start_ms = now_ms - self.WINDOW_HOURS * 3600000
        issues: Dict[str, List[Dict]] = {s: [] for s in SENSORS}
        has_data: Dict[str, bool] = {s: False for s in SENSORS}
        for table in sorted({q.table for q in QUANTITIES}):
            quantities = [q for q in QUANTITIES if q.table == table]
            stats, totals = self._minute_stats(table, [q.column for q in quantities], start_ms, now_ms)
            sensor = quantities[0].sensor
            covered = set()
            for q in quantities:
                minutes = stats.get(q.column, {})
                covered |= set(minutes)
                if minutes:
                    has_data[q.sensor] = True
                    issues[q.sensor] += self._check_quantity(q, minutes, totals.get(q.column, (0, 0)), now_minute)
            first = self._storage.first_sample_time(table)
            if covered and first is not None and table != "airthings_radon":  # the radon sensor is read every 5 minutes
                expected = min(self.WINDOW_HOURS * 60, (now_ms - int(first.timestamp() * 1000)) // 60000)
                if expected >= 60 and len(covered) < self.MIN_COMPLETENESS * expected:
                    issues[sensor].append({"code": "gaps", "severity": "warning",
                                           "params": {"sensor": sensor, "percent": round(100 * len(covered) / expected)}})
        for sensor, sensor_issues in self._historical_issues().items():
            issues[sensor] += sensor_issues
        self._issues, self._has_data = issues, has_data
        self._set_dust(dust_alarms or [])
        return True

    def _set_dust(self, dust_alarms: List[Dict]):
        if not hasattr(self, "_issues"):
            return
        issues = dict(self._issues)
        issues["pmsa003"] = [{"code": a["code"], "severity": "alarm", "params": a["params"], "dust": True} for a in dust_alarms]
        has_data = dict(self._has_data)
        has_data["pmsa003"] = has_data.get("pmsa003") or bool(self._storage.first_sample_time("pmsa003"))
        sensors = []
        for sensor in SENSORS:
            severities = {i["severity"] for i in issues[sensor]}
            status = "alarm" if "alarm" in severities else "warning" if severities else "ok" if has_data[sensor] else "no_data"
            sensors.append({"id": sensor, "status": status, "issues": issues[sensor]})
        self.report = {"sensors": sensors, "evaluated": datetime.fromtimestamp(self._clock(), tz=timezone.utc).isoformat()}
        # the maintenance alarms of the dust sensors are raised by their own monitor
        self.alarms = [i for s in sensors if s["id"] != "pmsa003" for i in s["issues"] if i["severity"] == "alarm"
                       or i["code"] == "co2_baseline_high"]

    def status_by_sensor(self) -> Dict[str, str]:
        return {s["id"]: s["status"] for s in self.report["sensors"]}

    def _historical_issues(self) -> Dict[str, List[Dict]]:
        baseline_start = self._storage.read_settings().get(self.SETTING_BASELINE_START, "")
        days = self._storage.read_sensor_daily(baseline_start)
        issues: Dict[str, List[Dict]] = {}
        groups: Dict[str, List[Quantity]] = {}
        for q in QUANTITIES:
            if q.compare:
                groups.setdefault(q.compare, []).append(q)
        for group, quantities in groups.items():
            for issue in self._drift(group, quantities, days):
                issues.setdefault(issue["params"]["sensor_id"], []).append(issue)
        co2 = self._co2_baseline(days)
        if co2:
            issues.setdefault("scd41", []).append(co2)
        return issues

    def _drift(self, group: str, quantities: List[Quantity], days: List[Tuple[str, Dict]]) -> List[Dict]:
        """Residual of each sensor (daily mean - median of the others), recent vs baseline days."""
        keys = {q.sensor: f"{q.sensor}.{q.name}" for q in quantities}
        residuals: Dict[str, List[float]] = {s: [] for s in keys}
        for _, stats in days:
            present = {s: stats[k]["mean"] for s, k in keys.items()
                       if k in stats and stats[k]["minutes"] >= self.MIN_DAY_MINUTES}
            if len(present) < 2:
                continue
            for sensor, value in present.items():
                others = [v for s, v in present.items() if s != sensor]
                residuals[sensor].append(value - statistics.median(others))
        threshold = DRIFT_THRESHOLDS[group]
        drifts = {}
        for sensor, values in residuals.items():
            if len(values) >= self.BASELINE_DAYS + self.RECENT_DAYS:
                drifts[sensor] = statistics.median(values[-self.RECENT_DAYS:]) - statistics.median(values[:self.BASELINE_DAYS])
        unit = quantities[0].unit
        if not drifts or max(abs(d) for d in drifts.values()) < threshold:
            return []
        if len(drifts) == 2:
            a, b = sorted(drifts)
            return [{"code": "drift_pair", "severity": "alarm",
                     "params": {"sensor_id": a, "sensor": a, "other": b, "quantity": group, "unit": unit,
                                "drift": round(abs(drifts[a]), 1)}}]
        # with 3 sensors or more, the drifting sensor is the one whose residual changed most
        sensor = max(drifts, key=lambda s: abs(drifts[s]))
        return [{"code": "drift", "severity": "alarm",
                 "params": {"sensor_id": sensor, "sensor": sensor, "quantity": group, "unit": unit,
                            "drift": round(drifts[sensor], 1)}}]

    def _co2_baseline(self, days: List[Tuple[str, Dict]]) -> Optional[Dict]:
        minima = [stats["scd41.co2"]["min_hourly"] for _, stats in days[-self.CO2_BASELINE_DAYS:]
                  if "scd41.co2" in stats and stats["scd41.co2"]["min_hourly"] is not None
                  and stats["scd41.co2"]["minutes"] >= self.MIN_DAY_MINUTES]
        if len(minima) < self.CO2_BASELINE_DAYS:
            return None
        lowest = round(min(minima))
        if lowest < self.CO2_BASELINE_LOW:
            return {"code": "co2_baseline_low", "severity": "alarm", "params": {"sensor": "scd41", "value": lowest}}
        if lowest > self.CO2_BASELINE_HIGH:
            return {"code": "co2_baseline_high", "severity": "warning", "params": {"sensor": "scd41", "value": lowest}}
        return None
