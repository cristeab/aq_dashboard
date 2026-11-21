#!/usr/bin/env python3
"""Mock of dust_sensor.py: two PMSA003 particle sensors plus the 10-minute
NowCast AQI computed from their mean PM2.5 concentration."""

from collections import deque
from datetime import timedelta
from types import SimpleNamespace
import random

from mock_common import SmoothSignal, cooking_intensity, parse_args, run_periodically

SENSOR_COUNT = 2
MEASUREMENT_WINDOW_LENGTH_SEC = 600  # 10 minutes, same as DustSensorUtils

# US EPA PM2.5 breakpoints: (C_low, C_high, AQI_low, AQI_high)
BREAKPOINTS_PM2_5 = [
    (0.0, 12.0, 0, 50),
    (12.1, 35.4, 51, 100),
    (35.5, 55.4, 101, 150),
    (55.5, 150.4, 151, 200),
    (150.5, 250.4, 201, 300),
    (250.5, 500.4, 301, 500),
]

# Typical PMSA003 particle counts (per 0.1 L) per ug/m3 of PM2.5
COUNT_RATIOS = {"gr03um": 180.0, "gr05um": 52.0, "gr10um": 9.0, "gr25um": 0.9, "gr50um": 0.25, "gr100um": 0.08}


def aqi_from_concentration(concentration):
    """Linear interpolation between the EPA breakpoints. Concentrations falling
    between two breakpoints (e.g. 12.05) use the upper interval."""
    concentration = max(0.0, concentration)
    for index, (c_low, c_high, aqi_low, aqi_high) in enumerate(BREAKPOINTS_PM2_5):
        is_last = index == len(BREAKPOINTS_PM2_5) - 1
        if concentration <= c_high or is_last:
            concentration = min(concentration, c_high)
            concentration = max(concentration, c_low)
            return round((aqi_high - aqi_low) / (c_high - c_low) * (concentration - c_low) + aqi_low, 1)


class NowCast:
    """Weighted average of the PM2.5 readings over the last 10 minutes, the
    same algorithm as DustSensorUtils._calculate_nowcast_aqi()."""

    def __init__(self):
        self._readings = deque()

    def add(self, timestamp, value):
        self._readings.append((timestamp, value))
        while timestamp - self._readings[0][0] > timedelta(seconds=MEASUREMENT_WINDOW_LENGTH_SEC):
            self._readings.popleft()

    def aqi(self):
        if len(self._readings) < 2:
            return None
        values = [value for _, value in self._readings]
        max_pm = max(values)
        scaled_rate_of_change = (max_pm - min(values)) / max_pm if max_pm else 0
        weight_factor = max(1 - scaled_rate_of_change, 0.5)
        last_timestamp = self._readings[-1][0]
        weighted_sum = weight_sum = 0.0
        for timestamp, value in self._readings:
            weight = weight_factor ** ((last_timestamp - timestamp).total_seconds() / MEASUREMENT_WINDOW_LENGTH_SEC)
            weighted_sum += value * weight
            weight_sum += weight
        return aqi_from_concentration(weighted_sum / weight_sum)


def make_sample(timestamp, pm25):
    pm25_cf1 = max(0, round(pm25))
    pm10_cf1 = max(0, round(pm25 * random.uniform(0.62, 0.72)))
    pm100_cf1 = max(pm25_cf1, round(pm25 * random.uniform(1.15, 1.35)))
    # atmospheric values equal CF=1 values at low concentration, lower above
    def std(value):
        return value if value < 30 else round(30 + (value - 30) * 0.67)
    counts = {name: max(0, round(pm25 * ratio * random.uniform(0.9, 1.1))) for name, ratio in COUNT_RATIOS.items()}
    return SimpleNamespace(
        timestamp=timestamp,
        pm10_cf1=pm10_cf1, pm25_cf1=pm25_cf1, pm100_cf1=pm100_cf1,
        pm10_std=std(pm10_cf1), pm25_std=std(pm25_cf1), pm100_std=std(pm100_cf1),
        **counts,
    )


# Faults of the second sensor, to check the health monitoring of the dust sensors
FAULTS = ("none", "drift", "disagree", "stuck", "missing")


def faulty_reading(fault, pm25, gain=1.6):
    """Reading of the second sensor with a fault: None when it sends nothing."""
    if fault == "drift":
        return pm25 * gain          # reads much more than at the installation
    if fault == "disagree":
        return pm25 * 3.0           # failing sensor (e.g. dirty optics), far beyond the 70 % US EPA criterion
    if fault == "stuck":
        return 7.0                  # constant value
    if fault == "missing":
        return None
    return pm25


def main():
    args = parse_args("Mocked PMSA003 dust sensors (replaces dust_sensor.py)", default_interval=1,
                      extra=lambda parser: parser.add_argument(
                          "--fault", choices=FAULTS, default="none",
                          help="simulate a fault of the second sensor (for the dust sensor health checks)"))
    background = SmoothSignal(initial=6.0, volatility=0.25, reversion=0.05, minimum=1.0)
    # the second sensor reads slightly higher, like a real sensor pair
    sensor_gain = [1.0, 1.06]
    nowcast = NowCast()

    def sample_once(storage, timestamp):
        pm25 = background.next(6.0) + 45.0 * cooking_intensity()
        values = [pm25 * gain * random.uniform(0.97, 1.03) for gain in sensor_gain]
        values[1] = faulty_reading(args.fault, values[1])
        samples = [make_sample(timestamp, v) for v in values if v is not None]
        for i, sample in enumerate(samples):
            storage.write_pm(i, sample)
        nowcast.add(timestamp, sum(s.pm25_cf1 for s in samples) / len(samples))
        aqi = nowcast.aqi()
        if aqi is not None:
            storage.write_aqi(timestamp, aqi)
        pm = " | ".join(f"#{i} PM1.0: {s.pm10_cf1}, PM2.5: {s.pm25_cf1}, PM10: {s.pm100_cf1} ug/m3"
                        for i, s in enumerate(samples))
        return f"10 min AQI: {aqi if aqi is not None else 'N/A'} | {pm}"

    run_periodically(args, sample_once)


if __name__ == "__main__":
    main()
