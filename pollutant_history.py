#!/usr/bin/env python3
"""
Rolling per-minute history of the pollutant concentrations, used to compute
the averages required by the air quality index profiles (10 min, 1 h, 8 h,
24 h means and NowCast).

Only the rows written since the previous refresh are queried (the current,
incomplete minute is re-read each time), so a refresh costs well under a
millisecond even with a full day of 1 Hz dust sensor data; only the first
refresh reads the last 24 hours.
"""

import math
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

# pollutant -> (table, column, unit of the stored values)
POLLUTANT_SOURCES = {
    "pm25": ("pmsa003", "pm25_cf1", "ug/m3"),  # both PMSA003 sensors are averaged
    "pm10": ("pmsa003", "pm100_cf1", "ug/m3"),
    "o3": ("zmod4510", "o3_ppb", "ppb"),
    "no2": ("zmod4510", "no2_ppb", "ppb"),
    "co": ("ze07co", "co_ppm", "ppm"),
    "co2": ("scd41", "co2", "ppm"),
}
# other quantities needed by the engines (e.g. the humidity correction of PM2.5);
# "energy(column)" aggregates 10^(L/10) to compute equivalent sound levels (LAeq)
AUXILIARY_SOURCES = {
    "rh": ("bme688", "relative_humidity", "%"),
    "noise": ("sound", "energy(sound_pressure_level)", "energy"),
}
SOURCES = {**POLLUTANT_SOURCES, **AUXILIARY_SOURCES}

HISTORY_MINUTES = 24 * 60
# An hourly (or shorter) average is valid when data is available for 75% of
# its minutes (US EPA: 45 minutes per hour)
MIN_BUCKET_COVERAGE = 0.75


@dataclass
class Bucket:
    """Statistics of one averaging bucket (e.g. one rolling hour)."""
    total: float = 0.0
    count: int = 0
    minutes_with_data: int = 0
    length_minutes: int = 60

    @property
    def mean(self) -> Optional[float]:
        return self.total / self.count if self.count else None

    @property
    def coverage(self) -> float:
        return min(1.0, self.minutes_with_data / self.length_minutes)

    @property
    def is_valid(self) -> bool:
        return self.count > 0 and self.coverage >= MIN_BUCKET_COVERAGE


class PollutantHistory:
    def __init__(self, storage, clock=time.time):
        self._storage = storage
        self._clock = clock
        self._tables: Dict[str, List[str]] = {}
        for table, column, _ in SOURCES.values():
            self._tables.setdefault(table, [])
            if column not in self._tables[table]:
                self._tables[table].append(column)
        # table -> {minute: {column or (column, sensor index): (sum, count)}}
        self._minutes: Dict[str, Dict[int, Dict]] = {t: {} for t in self._tables}
        self._next_minute: Dict[str, int] = {}
        self._now_minute: Optional[int] = None

    def refresh(self, now_ms: Optional[int] = None):
        now_ms = int(self._clock() * 1000) if now_ms is None else int(now_ms)
        now_minute = now_ms // 60000
        oldest_minute = now_minute - HISTORY_MINUTES + 1
        for table, columns in self._tables.items():
            start_minute = max(self._next_minute.get(table, oldest_minute), oldest_minute)
            rows = self._storage.read_minute_aggregates(table, columns, start_minute * 60000, now_ms)
            minutes = self._minutes[table]
            for minute in [m for m in minutes if m >= start_minute or m < oldest_minute]:
                del minutes[minute]
            for minute, values in rows:
                if values:
                    minutes[minute] = values
            # the current minute is incomplete: read it again next time
            self._next_minute[table] = now_minute
        self._now_minute = now_minute

    @property
    def now_minute(self) -> Optional[int]:
        return self._now_minute

    def buckets(self, pollutant: str, bucket_minutes: int, count: int, sensor: Optional[int] = None) -> List[Bucket]:
        """Rolling buckets ending now: bucket 0 holds the last bucket_minutes
        minutes (including the current one), bucket 1 the ones before, etc.
        With sensor, only the data of that sensor (e.g. dust sensor 0 or 1)."""
        if self._now_minute is None:
            raise RuntimeError("refresh() must be called first")
        table, column, _ = SOURCES[pollutant]
        if sensor is not None:
            column = (column, sensor)
        minutes = self._minutes[table]
        result = []
        for i in range(count):
            bucket = Bucket(length_minutes=bucket_minutes)
            last = self._now_minute - i * bucket_minutes
            for minute in range(last - bucket_minutes + 1, last + 1):
                values = minutes.get(minute)
                if values and column in values:
                    total, n = values[column]
                    bucket.total += total
                    bucket.count += n
                    bucket.minutes_with_data += 1
            result.append(bucket)
        return result


    def minute_means(self, pollutant: str, minutes: int, sensor: Optional[int] = None) -> Dict[int, float]:
        """{minute: mean} of the last minutes (minute 0 = the current one)."""
        table, column, _ = SOURCES[pollutant]
        if sensor is not None:
            column = (column, sensor)
        data = self._minutes[table]
        means = {}
        for age in range(minutes):
            values = data.get(self._now_minute - age)
            if values and column in values:
                total, count = values[column]
                means[age] = total / count
        return means


@dataclass
class Average:
    value: float
    provisional: bool  # not enough data for the averaging period, computed from the available data
    coverage: float    # fraction of the averaging period with data
    corrected: bool = False  # a correction (e.g. the humidity correction of PM2.5) was applied


# correction(value, relative humidity) -> corrected value
Correction = Callable[[float, float], float]


def _bucket_geometry(spec: Dict) -> Tuple[int, int]:
    if spec["type"] == "mean" and "minutes" in spec:
        return spec["minutes"], 1
    return 60, spec["hours"]


def _corrected(buckets: List[Bucket], rh_buckets: List[Bucket], correction: Correction) -> Optional[List[Bucket]]:
    """Applies the correction to the mean of each bucket with the mean humidity
    of the same bucket (or of the whole period when a bucket has no humidity)."""
    rh_total = sum(b.total for b in rh_buckets)
    rh_count = sum(b.count for b in rh_buckets)
    if rh_count == 0:
        return None
    fallback = rh_total / rh_count
    result = []
    for bucket, rh in zip(buckets, rh_buckets):
        if bucket.count:
            value = max(0.0, correction(bucket.mean, rh.mean if rh.count else fallback))
            bucket = Bucket(value * bucket.count, bucket.count, bucket.minutes_with_data, bucket.length_minutes)
        result.append(bucket)
    return result


def compute_average(history: PollutantHistory, pollutant: str, spec: Dict,
                    correction: Optional[Correction] = None) -> Optional[Average]:
    """Computes the average described by a profile averaging spec, or None if
    there is no data at all for the period. The optional correction is applied
    to each hourly (or shorter) mean before averaging, with the humidity of the
    same period; without humidity data the uncorrected values are used."""
    bucket_minutes, count = _bucket_geometry(spec)
    buckets = history.buckets(pollutant, bucket_minutes, count)
    corrected = False
    if correction is not None:
        corrected_buckets = _corrected(buckets, history.buckets("rh", bucket_minutes, count), correction)
        if corrected_buckets is not None:
            buckets, corrected = corrected_buckets, True
    if spec["type"] == "mean":
        average = _mean(buckets)
    else:
        average = _nowcast(buckets, spec["min_weight"])
    if average is not None:
        average.corrected = corrected
    return average


def _coverage(buckets: List[Bucket]) -> float:
    return sum(b.coverage for b in buckets) / len(buckets)


def _mean(buckets: List[Bucket]) -> Optional[Average]:
    valid = [b for b in buckets if b.is_valid]
    # e.g. 8 h mean: at least 6 valid hours, 24 h mean: at least 18 (US EPA / EU rules)
    if len(valid) >= math.ceil(MIN_BUCKET_COVERAGE * len(buckets)):
        return Average(sum(b.mean for b in valid) / len(valid), False, _coverage(buckets))
    total = sum(b.total for b in buckets)
    count = sum(b.count for b in buckets)
    if count == 0:
        return None
    return Average(total / count, True, _coverage(buckets))


def _nowcast(buckets: List[Bucket], min_weight: float) -> Optional[Average]:
    """US EPA NowCast: weighted average of the hourly means of the last hours,
    weight factor w = max(c_min / c_max, min_weight), hour i weighted by w^i.
    Valid if at least 2 of the 3 most recent hours are valid."""
    provisional = sum(1 for b in buckets[:3] if b.is_valid) < 2
    if provisional:
        hours = [(i, b.mean) for i, b in enumerate(buckets) if b.count > 0]
    else:
        hours = [(i, b.mean) for i, b in enumerate(buckets) if b.is_valid]
    if not hours:
        return None
    values = [c for _, c in hours]
    c_max = max(values)
    weight = max(min(values) / c_max, min_weight) if c_max > 0 else 1.0
    numerator = sum(weight ** i * c for i, c in hours)
    denominator = sum(weight ** i for i, _ in hours)
    return Average(numerator / denominator, provisional, _coverage(buckets))


def compute_energy_average(history: PollutantHistory, source: str, minutes: int) -> Optional[Average]:
    """Mean energy (10^(L/10)) over the last minutes of an "energy(...)" source,
    from rolling hours (or a single bucket below one hour), with the same
    validity rules as the means of the pollutants. LAeq = 10 log10(mean)."""
    if minutes <= 60:
        buckets = history.buckets(source, minutes, 1)
    else:
        buckets = history.buckets(source, 60, math.ceil(minutes / 60))
    return _mean(buckets)
