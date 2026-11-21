import math
import random

import pytest

from dust_sensor_monitor import DustSensorMonitor, alarm_message
from persistent_storage import PersistentStorage
from pollutant_history import PollutantHistory

DAY_MS = 86400000
NOW_MS = 1_800_000_000_000 // DAY_MS * DAY_MS + 15 * 3600000  # 15:00 UTC


class Logger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(message)

    warning = error = info


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setenv("AQ_DB_RETENTION_DAYS", "0")
    s = PersistentStorage(str(tmp_path / "dust.db"))
    yield s
    s.close()


def level(minute):
    """Typical indoor PM2.5 (ug/m3): daily cycle plus cooking peaks."""
    return 8 + 6 * math.sin(2 * math.pi * minute / 1440) + (25 if minute % 240 < 20 else 0)


def write(storage, days, sensor_b, sensor_a=level, end_minutes_ago=0, seed=1):
    """One sample per minute and per sensor, for `days` days ending end_minutes_ago before now."""
    rng = random.Random(seed)
    rows = []
    end = NOW_MS // 60000 - end_minutes_ago
    with storage.transaction():
        for minute in range(end - int(days * 1440) + 1, end + 1):
            a = sensor_a(minute) if sensor_a else None
            b = sensor_b(minute, a, rng) if sensor_b else None
            for sensor, value in ((0, a), (1, b)):
                if value is not None:
                    storage._write("pmsa003", minute * 60000 + 5000, {"sensor_index": sensor, "pm25_cf1": max(0, round(value))})
    return rows


def healthy(minute, a, rng):
    return a * 1.05 + rng.gauss(0, 0.5)


def monitor_for(storage, now_ms=NOW_MS):
    history = PollutantHistory(storage)
    history.refresh(now_ms)
    monitor = DustSensorMonitor(storage, history, Logger(), clock=lambda: now_ms / 1000)
    for _ in range(40):  # summarize the backlog of days (one day per call)
        monitor.evaluate(force=True)
    return monitor


def codes(monitor):
    return sorted(a["code"] for a in monitor.alarms)


def test_healthy_pair(storage):
    write(storage, 10, healthy)
    monitor = monitor_for(storage)
    assert codes(monitor) == []
    status = monitor.status
    assert status["state"] == "monitoring" and abs(status["drift"]) < 0.05 and status["recent_correlation"] > 0.95


def test_learning_before_enough_days(storage):
    write(storage, 4, healthy)
    monitor = monitor_for(storage)
    assert monitor.status["state"] == "learning" and codes(monitor) == []


def drifting_by(per_day):
    start = NOW_MS // 60000 - 10 * 1440

    def drifting(minute, a, rng):
        days = (minute - start) / 1440
        gain = 1.05 if days < 6 else 1.05 * (1 + per_day * (days - 6))  # sensor 2 reads more every day
        return a * gain + rng.gauss(0, 0.5)
    return drifting


def test_slow_drift(storage):
    write(storage, 10, drifting_by(0.20))
    monitor = monitor_for(storage)
    assert codes(monitor) == ["dust_sensors_drift"]
    alarm = monitor.alarms[0]
    assert alarm["params"]["drift_pct"] >= 30 and "replace the dust sensors" in alarm_message(alarm)
    assert monitor.status["state"] == "alarm"


def test_drift_below_the_alarm_threshold(storage):
    # +12 %/day for 4 days: the median of the last 3 days is 23 % above the baseline (alarm at 30 %)
    write(storage, 10, drifting_by(0.12))
    monitor = monitor_for(storage)
    assert codes(monitor) == [] and 0.15 < monitor.status["drift"] < 0.30


def test_disagreement(storage):
    write(storage, 2, healthy, end_minutes_ago=24 * 60)
    write(storage, 1, lambda minute, a, rng: a + 20, seed=2)  # sensor 2 reads 20 ug/m3 too much today
    monitor = monitor_for(storage)
    assert "dust_sensors_disagree" in codes(monitor)
    assert monitor.hourly["flagged_hours"] >= 6


def test_stuck_sensor(storage):
    write(storage, 1, healthy, end_minutes_ago=180)
    write(storage, 180 / 1440, lambda minute, a, rng: 7.0, sensor_a=lambda m: level(m) + 3 * math.sin(m / 7), seed=3)
    monitor = monitor_for(storage)
    stuck = [a for a in monitor.alarms if a["code"] == "dust_sensor_stuck"]
    assert len(stuck) == 1 and stuck[0]["params"] == {"sensor": 2, "value": 7.0}


def test_missing_sensor(storage):
    write(storage, 1, healthy, end_minutes_ago=60)
    write(storage, 60 / 1440, None)  # only sensor 1 in the last hour
    monitor = monitor_for(storage)
    assert [a["params"] for a in monitor.alarms if a["code"] == "dust_sensor_missing"] == [{"sensor": 2}]


def test_lost_correlation(storage):
    write(storage, 6, healthy, end_minutes_ago=4 * 1440)
    write(storage, 4, lambda minute, a, rng: rng.uniform(2, 30), seed=4)  # noise, unrelated to the particles
    monitor = monitor_for(storage)
    assert "dust_sensors_uncorrelated" in codes(monitor)


def test_reset_after_replacement(storage):
    start = NOW_MS // 60000 - 10 * 1440
    write(storage, 10, lambda minute, a, rng: a * (1.05 if minute - start < 6 * 1440 else 1.6))
    monitor = monitor_for(storage)
    assert "dust_sensors_drift" in codes(monitor)
    monitor.reset_baseline()
    monitor.evaluate(force=True)
    assert "dust_sensors_drift" not in codes(monitor)
    assert monitor.status["state"] == "learning" and monitor.status["baseline_start"] > monitor.status.get("evaluated", "")[:10]


def test_daily_statistics():
    means = {m: {0: 10.0 + m % 10, 1: 2 * (10.0 + m % 10)} for m in range(24 * 60)}
    record = DustSensorMonitor.daily_statistics(means)
    assert record["paired_minutes"] == 1440 and record["ratio"] == pytest.approx(2.0)
    assert record["correlation"] == pytest.approx(1.0) and record["valid_hours"] == 24
    # hourly means 14.5 and 29: difference 14.5 > 5 and 67 % < 70 %: not flagged
    assert record["flagged_hours"] == 0
