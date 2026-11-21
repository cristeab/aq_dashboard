import math
from datetime import datetime

import pytest

from comfort_engine import seasonal_clo
from noise_engine import NoiseEngine, period_at
from persistent_storage import PersistentStorage
from pollutant_history import PollutantHistory

NOW_MS = 1_800_000_000_000 // 60000 * 60000 + 30_000


@pytest.fixture
def history(tmp_path, monkeypatch):
    monkeypatch.setenv("AQ_DB_RETENTION_DAYS", "0")
    storage = PersistentStorage(str(tmp_path / "noise.db"))
    yield storage
    storage.close()


def write_levels(storage, levels_by_minute_ago):
    for minutes_ago, level in levels_by_minute_ago:
        storage.write_sound_pressure_level(NOW_MS - minutes_ago * 60000, level)


def test_equivalent_level_is_an_energy_average(history):
    # 30 minutes at 30 dB and 30 minutes at 50 dB: LAeq = 10 log10((10^3 + 10^5) / 2) = 47.0 dB, not 40 dB
    write_levels(history, [(m, 30.0 if m < 30 else 50.0) for m in range(60)])
    h = PollutantHistory(history)
    h.refresh(NOW_MS)
    result = NoiseEngine(h).compute("who_1999_indoor", moment=datetime(2027, 1, 1, 12, 0))
    assert result["value"] == round(10 * math.log10((1e3 + 1e5) / 2)) == 47
    assert not result["provisional"]


@pytest.mark.parametrize("room, hour, level, category, limit", [
    ("living", 12, 35, "within", 35), ("living", 2, 36, "slightly_above", 35),
    ("bedroom", 12, 33, "within", 35), ("bedroom", 2, 33, "slightly_above", 30),  # night limit 30 dB
    ("bedroom", 23, 39, "above", 30), ("bedroom", 23, 41, "far_above", 30), ("bedroom", 7, 47, "far_above", 35),
])
def test_who_limits_by_room_and_time(history, room, hour, level, category, limit):
    write_levels(history, [(m, level) for m in range(60)])
    h = PollutantHistory(history)
    h.refresh(NOW_MS)
    result = NoiseEngine(h).compute("who_1999_indoor", {"room": room}, datetime(2027, 1, 1, hour, 0))
    assert (result["category"], result["limit"]) == (category, limit)


def test_occupational_profiles(history):
    write_levels(history, [(m, 84.0) for m in range(480)])
    h = PollutantHistory(history)
    h.refresh(NOW_MS)
    engine = NoiseEngine(h)
    assert engine.compute("eu_2003_10_occupational")["category"] == "lower_action"   # 80 <= 84 < 85
    assert engine.compute("niosh_rel")["category"] == "action_level"                # 82 <= 84 < 85


def test_periods_across_midnight():
    periods = [{"id": "day", "from": "07:00", "to": "23:00", "limit": 35}, {"id": "night", "from": "23:00", "to": "07:00", "limit": 30}]
    assert [period_at(periods, datetime(2027, 1, 1, h, m))["id"] for h, m in ((6, 59), (7, 0), (22, 59), (23, 0), (0, 0))] == \
        ["night", "day", "day", "night", "night"]


def test_seasonal_clothing():
    assert seasonal_clo(datetime(2027, 7, 1)) == 0.5 and seasonal_clo(datetime(2027, 1, 15)) == 1.0
    assert seasonal_clo(datetime(2027, 1, 15), southern_hemisphere=True) == 0.5
    assert seasonal_clo(datetime(2027, 4, 15), southern_hemisphere=True) == 1.0
