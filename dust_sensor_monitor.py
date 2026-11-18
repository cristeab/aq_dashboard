#!/usr/bin/env python3
"""
Health monitoring of the two PMSA003 dust sensors.

Without a reference instrument, the correctness of the readings can only be
judged from the agreement of the two sensors, which should read alike when
they are healthy. The monitor raises maintenance alarms (shown in the
notifications) when one of the following is detected:

- disagreement: in the last 24 h, many hourly means of the two sensors differ
  by more than 5 µg/m³ and by more than 70 % (US EPA quality control of
  PurpleAir sensor pairs, Barkjohn et al., 2021);
- drift: the daily ratio of the readings of the two sensors (median of the
  minute ratios, at concentrations of at least 5 µg/m³) has moved by 30 % or
  more compared with the ratio of the first days after the installation
  (baseline). Relative drift is used because new sensors can differ by some
  percent from each other;
- lost correlation: the minute readings of the two sensors have been poorly
  correlated (r < 0.8) on the last 3 days (noisy or failing sensor, fan or laser);
- stuck sensor: a sensor reports a constant value for 3 hours while the other
  one varies;
- missing sensor: a sensor reports nothing for an hour while the other one does.

A drift of both sensors in the same direction cannot be detected without a
reference (e.g. a nearby official monitoring station).

The daily statistics are stored in the dust_sensor_daily table, so that the
baseline survives restarts and the retention of the raw data. After replacing
the sensors, reset_baseline() starts a new baseline.
"""

import statistics
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

DAY_MS = 86400000


# English texts of the alarms (for the log; the web interface translates them)
MESSAGES = {
    "dust_sensors_disagree": "The two dust sensors disagree in {flagged_hours} of the last {valid_hours} hours: "
                             "replace the dust sensors.",
    "dust_sensors_drift": "The readings of the two dust sensors have drifted apart by {drift_pct} % since {since}: "
                          "replace the dust sensors.",
    "dust_sensors_uncorrelated": "The readings of the two dust sensors have been poorly correlated (r = {correlation}) "
                                 "on the last 3 days: replace the dust sensors.",
    "dust_sensor_stuck": "Dust sensor {sensor} has reported the same value ({value} µg/m³) for 3 hours: replace it.",
    "dust_sensor_missing": "Dust sensor {sensor} sends no data: check its connection or replace it.",
}


def _correlation(left, right):
    """Pearson correlation compatible with Python versions before 3.10."""
    if hasattr(statistics, "correlation"):
        return statistics.correlation(left, right)
    mean_left, mean_right = statistics.fmean(left), statistics.fmean(right)
    numerator = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    denominator = (sum((a - mean_left) ** 2 for a in left) *
                   sum((b - mean_right) ** 2 for b in right)) ** 0.5
    return numerator / denominator if denominator else 0.0


def alarm_message(alarm: Dict) -> str:
    return MESSAGES[alarm["code"]].format(**alarm["params"])


class DustSensorMonitor:
    COLUMN = "pm25_cf1"
    SENSORS = (0, 1)
    EVALUATION_INTERVAL_SEC = 60
    HISTORY_DAYS = 30
    # disagreement (US EPA quality control of sensor pairs)
    DISAGREEMENT_ABSOLUTE = 5.0       # µg/m³
    DISAGREEMENT_RELATIVE = 0.70      # relative percent difference
    DISAGREEMENT_MIN_HOURS = 6
    DISAGREEMENT_MIN_FRACTION = 0.25
    MIN_VALID_HOURS = 8
    MIN_HOUR_MINUTES = 45
    # stuck / missing sensor
    STUCK_WINDOW_MINUTES = 180
    STUCK_MIN_MINUTES = 120
    STUCK_OTHER_RANGE = 3.0           # µg/m³ variation of the other sensor
    MISSING_WINDOW_MINUTES = 60
    # drift and correlation (daily statistics)
    RATIO_MIN_LEVEL = 5.0             # µg/m³, lower concentrations are dominated by the 1 µg/m³ resolution
    RATIO_MIN_MINUTES = 60
    MIN_DAY_PAIRED_MINUTES = 12 * 60
    CORRELATION_MIN_STD = 0.5
    BASELINE_DAYS = 5
    RECENT_DAYS = 3
    DRIFT_ALARM = 0.30
    CORRELATION_ALARM = 0.80
    SETTING_BASELINE_START = "dust_baseline_start"

    def __init__(self, storage, history, logger, clock=time.time):
        self._storage = storage
        self._history = history
        self._logger = logger
        self._clock = clock
        self._last_evaluation = 0.0
        self.alarms: List[Dict] = []
        self.hourly: Optional[Dict] = None
        self.status: Dict = {"state": "learning"}

    # ------------------------------------------------------------ statistics

    @classmethod
    def _is_disagreement(cls, a: float, b: float) -> bool:
        difference = abs(a - b)
        mean = (a + b) / 2.0
        return difference > cls.DISAGREEMENT_ABSOLUTE and mean > 0 and difference / mean > cls.DISAGREEMENT_RELATIVE

    @classmethod
    def daily_statistics(cls, minute_means: Dict[int, Dict[int, float]]) -> Dict:
        """Statistics of one day from {minute: {sensor: mean}}."""
        pairs = [(v[0], v[1]) for _, v in sorted(minute_means.items()) if 0 in v and 1 in v]
        record = {"paired_minutes": len(pairs), "mean_a": None, "mean_b": None, "ratio": None,
                  "correlation": None, "valid_hours": 0, "flagged_hours": 0}
        if not pairs:
            return record
        a_values = [a for a, _ in pairs]
        b_values = [b for _, b in pairs]
        record["mean_a"] = statistics.fmean(a_values)
        record["mean_b"] = statistics.fmean(b_values)
        ratios = [b / a for a, b in pairs if a > 0 and (a + b) / 2.0 >= cls.RATIO_MIN_LEVEL]
        if len(ratios) >= cls.RATIO_MIN_MINUTES:
            record["ratio"] = statistics.median(ratios)
        if (len(pairs) >= cls.RATIO_MIN_MINUTES and statistics.pstdev(a_values) >= cls.CORRELATION_MIN_STD
                and statistics.pstdev(b_values) >= cls.CORRELATION_MIN_STD):
            record["correlation"] = _correlation(a_values, b_values)
        hours: Dict[int, List] = {}
        for minute, values in minute_means.items():
            if 0 in values and 1 in values:
                hours.setdefault(minute // 60, []).append((values[0], values[1]))
        for hour_pairs in hours.values():
            if len(hour_pairs) >= cls.MIN_HOUR_MINUTES:
                record["valid_hours"] += 1
                a = statistics.fmean(p[0] for p in hour_pairs)
                b = statistics.fmean(p[1] for p in hour_pairs)
                record["flagged_hours"] += cls._is_disagreement(a, b)
        return record

    # ------------------------------------------------------------ evaluation

    def baseline_start(self) -> Optional[str]:
        return self._storage.read_settings().get(self.SETTING_BASELINE_START)

    def reset_baseline(self):
        """To be called after replacing the sensors: the drift is measured again
        from a new baseline, built from the next complete days (the current day
        mixes the readings of the old and of the new sensors)."""
        tomorrow = self._day((int(self._clock() * 1000) // DAY_MS + 1) * DAY_MS)
        self._storage.write_settings({self.SETTING_BASELINE_START: tomorrow})
        self._last_evaluation = 0.0
        self._logger.info(f"Dust sensor baseline reset, new baseline from {tomorrow}")

    def _summarize_missing_day(self, now: float) -> bool:
        """Stores the statistics of the oldest complete day that has none yet
        (one day per call, so that a long backlog does not block an update)."""
        today_start = int(now * 1000) // DAY_MS * DAY_MS
        first = self._storage.first_sample_time("pmsa003")
        if first is None:
            return False
        start = max(int(first.timestamp() * 1000) // DAY_MS * DAY_MS, today_start - self.HISTORY_DAYS * DAY_MS)
        known = {r["day"] for r in self._storage.read_dust_daily(self._day(start))}
        for day_start in range(start, today_start, DAY_MS):
            day = self._day(day_start)
            if day in known:
                continue
            means = self._storage.read_sensor_minute_means("pmsa003", self.COLUMN, day_start, day_start + DAY_MS - 1)
            self._storage.write_dust_daily(day, self.daily_statistics(means))
            return True
        return False

    @staticmethod
    def _day(ms: int) -> str:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")

    def evaluate(self, force: bool = False) -> bool:
        """Runs the checks (at most every EVALUATION_INTERVAL_SEC unless forced).
        Must be called after the history has been refreshed. Returns True if
        the checks were run."""
        now = self._clock()
        backlog = self._summarize_missing_day(now)
        if not force and not backlog and now - self._last_evaluation < self.EVALUATION_INTERVAL_SEC:
            return False
        self._last_evaluation = now
        alarms = self._acute_alarms()
        drift_status, drift_alarms = self._drift()
        alarms += drift_alarms
        self.alarms = alarms
        self.status = {**drift_status, "alarms": alarms, "evaluated": datetime.fromtimestamp(now, tz=timezone.utc).isoformat()}
        return True

    def _acute_alarms(self) -> List[Dict]:
        alarms = []
        history = self._history
        # missing sensor
        minutes = {s: history.minute_means("pm25", self.MISSING_WINDOW_MINUTES, sensor=s) for s in self.SENSORS}
        for sensor, other in ((0, 1), (1, 0)):
            if not minutes[sensor] and len(minutes[other]) >= 0.75 * self.MISSING_WINDOW_MINUTES:
                alarms.append({"code": "dust_sensor_missing", "params": {"sensor": sensor + 1}})
        # stuck sensor
        window = {s: history.minute_means("pm25", self.STUCK_WINDOW_MINUTES, sensor=s) for s in self.SENSORS}
        for sensor, other in ((0, 1), (1, 0)):
            values, other_values = list(window[sensor].values()), list(window[other].values())
            if (len(values) >= self.STUCK_MIN_MINUTES and len(other_values) >= self.STUCK_MIN_MINUTES
                    and max(values) - min(values) == 0
                    and max(other_values) - min(other_values) >= self.STUCK_OTHER_RANGE):
                alarms.append({"code": "dust_sensor_stuck", "params": {"sensor": sensor + 1, "value": values[0]}})
        # disagreement of the hourly means of the last 24 hours
        buckets = {s: history.buckets("pm25", 60, 24, sensor=s) for s in self.SENSORS}
        valid = flagged = 0
        for a, b in zip(buckets[0], buckets[1]):
            if a.is_valid and b.is_valid:
                valid += 1
                flagged += self._is_disagreement(a.mean, b.mean)
        self.hourly = {"valid_hours": valid, "flagged_hours": flagged}
        if (valid >= self.MIN_VALID_HOURS and flagged >= self.DISAGREEMENT_MIN_HOURS
                and flagged >= self.DISAGREEMENT_MIN_FRACTION * valid):
            alarms.append({"code": "dust_sensors_disagree", "params": {"flagged_hours": flagged, "valid_hours": valid}})
        return alarms

    def _drift(self):
        baseline_start = self.baseline_start() or ""
        records = [r for r in self._storage.read_dust_daily(baseline_start)
                   if r["paired_minutes"] >= self.MIN_DAY_PAIRED_MINUTES]
        with_ratio = [r for r in records if r["ratio"] is not None]
        status = {
            "baseline_start": baseline_start or (records[0]["day"] if records else None),
            "days": len(records),
            "baseline_ratio": None, "recent_ratio": None, "drift": None, "recent_correlation": None,
            "hourly": self.hourly,
            "state": "learning",
        }
        alarms = []
        if len(with_ratio) >= self.BASELINE_DAYS + self.RECENT_DAYS:
            baseline = statistics.median(r["ratio"] for r in with_ratio[:self.BASELINE_DAYS])
            recent = statistics.median(r["ratio"] for r in with_ratio[-self.RECENT_DAYS:])
            drift = recent / baseline - 1.0
            status.update(baseline_ratio=round(baseline, 3), recent_ratio=round(recent, 3), drift=round(drift, 3),
                          state="monitoring")
            if abs(drift) >= self.DRIFT_ALARM:
                alarms.append({"code": "dust_sensors_drift",
                               "params": {"drift_pct": round(drift * 100), "since": with_ratio[0]["day"]}})
        correlated = [r for r in records if r["correlation"] is not None][-self.RECENT_DAYS:]
        if correlated:
            status["recent_correlation"] = round(min(r["correlation"] for r in correlated), 3)
        if len(correlated) == self.RECENT_DAYS and all(r["correlation"] < self.CORRELATION_ALARM for r in correlated):
            alarms.append({"code": "dust_sensors_uncorrelated", "params": {"correlation": round(
                max(r["correlation"] for r in correlated), 2)}})
        if alarms:
            status["state"] = "alarm"
        return status, alarms

