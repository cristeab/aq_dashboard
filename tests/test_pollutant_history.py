import pytest

from persistent_storage import PersistentStorage
from pollutant_history import PollutantHistory, compute_average

NOW_MS = 1_800_000_000_000 // 60000 * 60000 + 30_000  # 30 s into a minute


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setenv("AQ_DB_RETENTION_DAYS", "0")
    s = PersistentStorage(str(tmp_path / "test.db"))
    yield s
    s.close()


def write_co(storage, minutes_ago, value, per_minute=1):
    for k in range(per_minute):
        storage.write_co_data(NOW_MS - minutes_ago * 60000 - k * 1000, value)


def test_hourly_buckets_and_coverage(storage):
    for m in range(0, 120):          # 2 hours of data, one sample per minute
        write_co(storage, m, 1.0 if m < 60 else 3.0)
    history = PollutantHistory(storage)
    history.refresh(NOW_MS)
    b0, b1, b2 = history.buckets("co", 60, 3)
    assert (b0.mean, b0.coverage, b0.is_valid) == (1.0, 1.0, True)
    assert (b1.mean, b1.coverage) == (3.0, 1.0)
    assert b2.count == 0 and b2.mean is None


def test_incremental_refresh_does_not_duplicate(storage):
    write_co(storage, 5, 2.0, per_minute=3)
    history = PollutantHistory(storage)
    history.refresh(NOW_MS)
    write_co(storage, 0, 8.0)             # new sample in the current minute
    history.refresh(NOW_MS + 1000)
    history.refresh(NOW_MS + 2000)        # refreshing again must not count rows twice
    bucket = history.buckets("co", 10, 1)[0]
    assert bucket.count == 4 and bucket.mean == pytest.approx((3 * 2.0 + 8.0) / 4)


def test_old_minutes_expire(storage):
    write_co(storage, 24 * 60 - 1, 5.0)   # still within the 24 h history
    history = PollutantHistory(storage)
    history.refresh(NOW_MS)
    assert history.buckets("co", 60, 24)[23].count == 1
    history.refresh(NOW_MS + 2 * 60000)   # two minutes later it is gone
    assert history.buckets("co", 60, 24)[23].count == 0


def test_mean_needs_75_percent_of_the_hours(storage):
    for m in range(0, 5 * 60):            # 5 of 8 hours with data
        write_co(storage, m, 2.0)
    history = PollutantHistory(storage)
    history.refresh(NOW_MS)
    average = compute_average(history, "co", {"type": "mean", "hours": 8})
    assert average.value == pytest.approx(2.0) and average.provisional and average.coverage == pytest.approx(5 / 8)
    for m in range(5 * 60, 6 * 60):       # 6 of 8 hours: valid
        write_co(storage, m, 2.0)
    history = PollutantHistory(storage)
    history.refresh(NOW_MS)
    assert not compute_average(history, "co", {"type": "mean", "hours": 8}).provisional


def test_nowcast(storage):
    for m in range(0, 180):               # hourly means 30, 20, 10 (most recent first)
        write_co(storage, m, [30.0, 20.0, 10.0][m // 60])
    history = PollutantHistory(storage)
    history.refresh(NOW_MS)
    average = compute_average(history, "co", {"type": "nowcast", "hours": 12, "min_weight": 0.5})
    # w = 10 / 30 < 0.5 -> 0.5: (30 + 0.5 * 20 + 0.25 * 10) / (1 + 0.5 + 0.25)
    assert average.value == pytest.approx(42.5 / 1.75) and not average.provisional


def test_nowcast_needs_two_of_the_last_three_hours(storage):
    for m in range(0, 30):                # only half an hour of data
        write_co(storage, m, 4.0)
    history = PollutantHistory(storage)
    history.refresh(NOW_MS)
    average = compute_average(history, "co", {"type": "nowcast", "hours": 12, "min_weight": 0.5})
    assert average.value == pytest.approx(4.0) and average.provisional
    assert compute_average(history, "pm25", {"type": "nowcast", "hours": 12, "min_weight": 0.5}) is None


def write_pm(storage, minutes_ago, a, b):
    from types import SimpleNamespace
    t = NOW_MS - minutes_ago * 60000
    for sensor, value in ((0, a), (1, b)):
        storage.write_pm(sensor, SimpleNamespace(timestamp=t, pm10_cf1=0, pm25_cf1=value, pm100_cf1=value, pm10_std=0, pm25_std=0,
                                                 pm100_std=0, gr03um=0, gr05um=0, gr10um=0, gr25um=0, gr50um=0, gr100um=0))


def test_per_sensor_buckets(storage):
    for m in range(60):
        write_pm(storage, m, 10, 30)
    history = PollutantHistory(storage)
    history.refresh(NOW_MS)
    assert history.buckets("pm25", 60, 1)[0].mean == 20          # both sensors
    assert history.buckets("pm25", 60, 1, sensor=0)[0].mean == 10
    assert history.buckets("pm25", 60, 1, sensor=1)[0].mean == 30
    assert history.minute_means("pm25", 3, sensor=1) == {0: 30, 1: 30, 2: 30}


def test_humidity_correction_per_hour(storage):
    from pm_correction import barkjohn_2021
    for m in range(120):
        write_pm(storage, m, 20, 20)
        storage.write_ambient_data(NOW_MS - m * 60000, 22.0, 1, 40.0 if m < 60 else 80.0, 1013, 50)
    history = PollutantHistory(storage)
    history.refresh(NOW_MS)
    corrected = compute_average(history, "pm25", {"type": "mean", "hours": 2}, barkjohn_2021)
    # each hour is corrected with its own humidity, then averaged
    assert corrected.corrected and corrected.value == pytest.approx((barkjohn_2021(20, 40) + barkjohn_2021(20, 80)) / 2)
    raw = compute_average(history, "pm25", {"type": "mean", "hours": 2})
    assert not raw.corrected and raw.value == 20


def test_correction_without_humidity_uses_raw_values(storage):
    from pm_correction import barkjohn_2021
    for m in range(60):
        write_pm(storage, m, 20, 20)
    history = PollutantHistory(storage)
    history.refresh(NOW_MS)
    average = compute_average(history, "pm25", {"type": "mean", "minutes": 10}, barkjohn_2021)
    assert not average.corrected and average.value == 20
