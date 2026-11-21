import math
import random

import pytest

from persistent_storage import PersistentStorage
from sensor_validation import SensorValidator, issue_message

DAY_MS = 86400000
NOW_MS = 1_800_000_000_000 // DAY_MS * DAY_MS + 15 * 3600000  # 15:00 UTC


class Logger:
    def info(self, message):
        pass

    warning = error = info


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setenv("AQ_DB_RETENTION_DAYS", "0")
    s = PersistentStorage(str(tmp_path / "validation.db"))
    yield s
    s.close()


def write(storage, days, table, values, end_minutes_ago=0, seed=1):
    """One sample per minute; values(minute, rng) -> {column: value} or None."""
    rng = random.Random(seed)
    end = NOW_MS // 60000 - end_minutes_ago
    with storage.transaction():
        for minute in range(end - int(days * 1440) + 1, end + 1):
            fields = values(minute, rng)
            if fields:
                storage._write(table, minute * 60000 + 7000, fields)


def temperature(minute, rng, offset=0.0):
    return 21 + 2 * math.sin(2 * math.pi * minute / 1440) + offset + rng.gauss(0, 0.05)


def healthy(storage, days=10, bme_offset=lambda minute: 0.0, co2_floor=430):
    write(storage, days, "bme688", lambda m, r: {"temperature": temperature(m, r, 1.5 + bme_offset(m)),  # self-heating
                                                 "relative_humidity": 45 + r.gauss(0, 0.3), "pressure": 1012 + r.gauss(0, 0.05),
                                                 "gas_resistance": 1e5, "iaq": 50})
    write(storage, days, "scd41", lambda m, r: {"temperature": temperature(m, r, 0.8), "relative_humidity": 43 + r.gauss(0, 0.3),
                                                "co2": round(co2_floor + 400 * max(0, math.sin(2 * math.pi * m / 1440)) + r.gauss(0, 5))}, seed=2)
    write(storage, days, "bmp390l", lambda m, r: {"temperature": temperature(m, r), "pressure": 1011.5 + r.gauss(0, 0.05),
                                                  "altitude": 100}, seed=3)


def validator_for(storage):
    validator = SensorValidator(storage, Logger(), clock=lambda: NOW_MS / 1000)
    for _ in range(40):  # summarize the backlog of days
        validator.evaluate(force=True)
    return validator


def issues(validator, sensor):
    return {i["code"]: i for s in validator.report["sensors"] if s["id"] == sensor for i in s["issues"]}


def test_healthy_sensors(storage):
    healthy(storage)
    validator = validator_for(storage)
    status = validator.status_by_sensor()
    assert status["bme688"] == status["scd41"] == status["bmp390l"] == "ok"
    assert status["sgp41"] == "no_data" and validator.alarms == []


def test_out_of_range(storage):
    write(storage, 1, "bme688", lambda m, r: {"temperature": 21 + r.gauss(0, 0.1), "pressure": 1012 + r.gauss(0, 0.1),
                                              "relative_humidity": 120 if m % 10 == 0 else 45 + r.gauss(0, 0.3)})
    issue = issues(validator_for(storage), "bme688")["out_of_range"]
    assert issue["severity"] == "alarm" and issue["params"]["quantity"] == "relative_humidity" and issue["params"]["count"] >= 143  # the sample of the current minute is after "now"
    assert "outside the valid range" in issue_message(issue)


def test_stuck_sensor(storage):
    write(storage, 1, "bme688", lambda m, r: {"temperature": 21.37, "relative_humidity": 45 + r.gauss(0, 0.3),
                                              "pressure": 1012 + r.gauss(0, 0.05)})
    validator = validator_for(storage)
    issue = issues(validator, "bme688")["stuck"]
    assert issue["params"]["quantity"] == "temperature" and issue["params"]["value"] == 21.37
    assert validator.status_by_sensor()["bme688"] == "alarm" and validator.alarms


def test_jumps(storage):
    write(storage, 1, "bme688", lambda m, r: {"temperature": 21 + (6 if m % 180 == 0 else 0) + r.gauss(0, 0.05),
                                              "relative_humidity": 45 + r.gauss(0, 0.3), "pressure": 1012 + r.gauss(0, 0.05)})
    issue = issues(validator_for(storage), "bme688")["jumps"]
    assert issue["severity"] == "warning" and issue["params"]["count"] >= 3


def test_gaps(storage):
    write(storage, 1, "bme688", lambda m, r: {"temperature": 21 + r.gauss(0, 0.1)} if m % 2 else None)
    assert issues(validator_for(storage), "bme688")["gaps"]["params"]["percent"] == 50


def test_drifting_sensor_is_identified(storage):
    start = NOW_MS // 60000 - 10 * 1440
    healthy(storage, bme_offset=lambda m: 0.0 if m - start < 6 * 1440 else 3.0)  # BME688 reads 3 C more
    validator = validator_for(storage)
    drift = issues(validator, "bme688")["drift"]
    assert drift["params"]["quantity"] == "temperature" and drift["params"]["drift"] == pytest.approx(3.0, abs=0.3)
    assert "drift" not in issues(validator, "scd41") and "drift" not in issues(validator, "bmp390l")


def test_pressure_drift_of_two_sensors(storage):
    start = NOW_MS // 60000 - 10 * 1440
    write(storage, 10, "bme688", lambda m, r: {"pressure": 1012 + (0 if m - start < 6 * 1440 else 4) + r.gauss(0, 0.05)})
    write(storage, 10, "bmp390l", lambda m, r: {"pressure": 1011.5 + r.gauss(0, 0.05)}, seed=2)
    found = [i for s in validator_for(storage).report["sensors"] for i in s["issues"] if i["code"] == "drift_pair"]
    assert len(found) == 1 and found[0]["params"]["quantity"] == "pressure" and found[0]["params"]["drift"] == pytest.approx(4, abs=0.3)


@pytest.mark.parametrize("floor, code", [(340, "co2_baseline_low"), (620, "co2_baseline_high"), (430, None)])
def test_co2_baseline(storage, floor, code):
    healthy(storage, co2_floor=floor)
    found = issues(validator_for(storage), "scd41")
    assert (code in found) if code else not {"co2_baseline_low", "co2_baseline_high"} & set(found)


def test_dust_alarms_are_part_of_the_report(storage):
    healthy(storage, days=1)
    validator = validator_for(storage)
    validator.evaluate(dust_alarms=[{"code": "dust_sensors_drift", "params": {"drift_pct": 35, "since": "2027-01-01"}}])
    assert validator.status_by_sensor()["pmsa003"] == "alarm"
    assert all(not i.get("dust") for i in validator.alarms)  # raised by the dust sensor monitor itself
