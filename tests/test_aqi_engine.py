import pytest

from aqi_engine import (AqiEngine, breakpoint_index, convert_concentration, round_concentration, round_index)
from pollutant_history import Average
from profile_loader import load_profiles

AQI = load_profiles("aqi")


def table(profile_id, pollutant, index=0):
    return AQI[profile_id]["pollutants"][pollutant][index]


def sub_index(profile_id, pollutant, concentration, index=0):
    t = table(profile_id, pollutant, index)
    c = round_concentration(concentration, t["decimals"], t["rounding"])
    result = breakpoint_index(c, t)
    return None if result is None else (round_index(result[0], AQI[profile_id]["index_rounding"]), result[1])


@pytest.mark.parametrize("concentration, expected", [
    (0.0, 0), (9.0, 50), (9.05, 50),   # 9.05 is truncated to 9.0
    (9.1, 51), (12.0, 56), (35.4, 100), (35.5, 101), (55.4, 150), (125.4, 200), (225.5, 301), (325.4, 500),
])
def test_us_epa_pm25_2024_breakpoints(concentration, expected):
    assert sub_index("us_epa", "pm25", concentration) == (expected, False)


def test_us_epa_above_the_aqi_is_capped():
    assert sub_index("us_epa", "pm25", 400.0) == (500, True)


def test_us_epa_ozone_reference_example():
    # EPA example: 8-hour ozone of 0.078 ppm -> AQI 126
    assert sub_index("us_epa", "o3", 0.078) == (126, False)
    # 0.0789 is truncated to 0.078
    assert sub_index("us_epa", "o3", 0.0789) == (126, False)


def test_us_epa_ozone_one_hour_table_only_from_0_125_ppm():
    assert sub_index("us_epa", "o3", 0.100, index=1) is None
    assert sub_index("us_epa", "o3", 0.130, index=1) == (107, False)
    # the 8-hour table does not apply above 0.200 ppm
    assert sub_index("us_epa", "o3", 0.250, index=0) is None


@pytest.mark.parametrize("pollutant, concentration, expected", [
    ("co", 5.0, 56), ("co", 4.4, 50), ("no2", 53, 50), ("no2", 54, 51), ("no2", 100, 100), ("pm10", 154, 100),
])
def test_us_epa_other_pollutants(pollutant, concentration, expected):
    assert sub_index("us_epa", pollutant, concentration) == (expected, False)


def test_china_rounds_sub_indices_up():
    # PM2.5 80 ug/m3: 100 + (150 - 100) / (115 - 75) * (80 - 75) = 106.25 -> 107
    assert sub_index("china_mee", "pm25", 80) == (107, False)
    assert sub_index("china_mee", "pm10", 150) == (100, False)
    # O3 8 h above 800 ug/m3: only the 1 h table applies
    assert sub_index("china_mee", "o3", 900, index=1) is None
    assert sub_index("china_mee", "o3", 900, index=0) == (350, False)


def test_caqi():
    assert sub_index("eu_caqi", "pm10", 60) == (56, False)   # 50 + 25 / 40 * 10 = 56.25
    assert sub_index("eu_caqi", "no2", 450) == (100, True)   # above the grid: "very high", shown as >100
    assert sub_index("eu_caqi", "co", 6250) == (38, False)   # 25 + 25 / 2500 * 1250 = 37.5 -> 38


def test_concentration_conversions():
    assert convert_concentration(1.0, "no2", "ppb", "ug/m3", 25) == pytest.approx(1.8804, abs=1e-4)
    assert convert_concentration(1.0, "no2", "ppb", "ug/m3", 20) == pytest.approx(1.9126, abs=1e-4)
    assert convert_concentration(1.0, "o3", "ppb", "ug/m3", 25) == pytest.approx(1.9619, abs=1e-4)
    assert convert_concentration(1.0, "co", "ppm", "mg/m3", 25) == pytest.approx(1.1449, abs=1e-4)
    assert convert_concentration(1.0, "co", "ppm", "ug/m3", 20) == pytest.approx(1164.4, abs=0.1)
    assert convert_concentration(78.0, "o3", "ppb", "ppm", 25) == pytest.approx(0.078)
    assert convert_concentration(12.3, "pm25", "ug/m3", "ug/m3", 25) == 12.3


@pytest.mark.parametrize("value, decimals, mode, expected", [
    (0.07, 3, "truncate", 0.07), (0.0789, 3, "truncate", 0.078), (35.46, 1, "truncate", 35.4),
    (35.45, 1, "round", 35.5), (2.5, 0, "round", 3.0),
])
def test_concentration_rounding(value, decimals, mode, expected):
    assert round_concentration(value, decimals, mode) == pytest.approx(expected)


def test_index_rounding():
    assert round_index(50.5, "nearest") == 51
    assert round_index(106.25, "ceil") == 107
    assert round_index(100.0, "ceil") == 100


CO2 = load_profiles("co2")


class FakeEngine(AqiEngine):
    """Engine with fixed averages per (pollutant, averaging) instead of a database."""

    def __init__(self, averages, profiles=None):
        super().__init__(storage=None, profiles=profiles or {**AQI, **CO2})
        self.averages = averages

    def _averaged(self, profile, pollutant, spec):
        key = (pollutant, spec["averaging"].get("hours"), spec["averaging"].get("minutes"))
        if key not in self.averages:
            return None
        value, provisional = self.averages[key]
        from aqi_engine import POLLUTANT_SOURCES
        converted = convert_concentration(value, pollutant, POLLUTANT_SOURCES[pollutant][2], spec["unit"],
                                          profile["gas_reference_temperature_c"])
        return round_concentration(converted, spec["decimals"], spec["rounding"]), Average(value, provisional, 1.0)


def test_overall_index_is_the_highest_sub_index():
    engine = FakeEngine({("pm25", 12, None): (12.0, False), ("no2", 1, None): (40, True), ("o3", 8, None): (20, False)})
    result = engine.compute("us_epa")
    assert result["sub_indices"]["pm25"]["value"] == 56   # 51 + 49 / 26.3 * 2.9 = 56.4
    assert result["sub_indices"]["no2"]["value"] == 38    # 50 / 53 * 40 = 37.7
    assert result["sub_indices"]["o3"]["value"] == 19     # 0.020 ppm: 50 / 0.054 * 0.020 = 18.5
    assert result["value"] == 56 and result["dominant"] == ["pm25"] and result["category"] == "moderate"
    assert result["provisional"] is False  # only the leading pollutant matters (NO2 is provisional)


def test_ties_and_provisional_leader():
    # NO2 60 ppb: (100 - 51) / (100 - 54) * (60 - 54) + 51 = 57.4 -> 57, higher than PM2.5 (56)
    engine = FakeEngine({("pm25", 12, None): (12.0, False), ("no2", 1, None): (60, True)})
    result = engine.compute("us_epa")
    assert result["value"] == 57 and result["dominant"] == ["no2"] and result["provisional"] is True


def test_china_primary_pollutant_only_above_50():
    engine = FakeEngine({("pm25", 24, None): (20.0, False)})
    result = engine.compute("china_mee")
    assert result["value"] == 29 and result["dominant"] == [] and result["category"] == "excellent"


def test_caqi_above_scale_is_very_high():
    engine = FakeEngine({("no2", 1, None): (300.0, False)})  # 300 ppb = 574 ug/m3 at 20 C
    result = engine.compute("eu_caqi")
    assert result["display"] == ">100" and result["category"] == "very_high" and result["above_scale"]


def test_raw_concentration_profile():
    engine = FakeEngine({("pm25", None, 10): (16.04, False), ("no2", None, 10): (10.0, False)})
    result = engine.compute("raw_who", {"pollutant": "pm25"})
    assert result["kind"] == "concentration" and result["display"] == "16.0" and result["category"] == "it4"
    result = engine.compute("raw_who", {"pollutant": "no2"})
    assert result["value"] == 19 and result["unit"] == "µg/m³" and result["category"] == "aqg"  # 10 ppb = 18.8
    assert engine.compute("raw_who", {"pollutant": "co"}) is None  # no CO data
    assert engine.compute("raw_who", {"pollutant": "bogus"})["pollutant"] == "pm25"  # falls back to the default


def test_no_data_gives_no_index():
    assert FakeEngine({}).compute("us_epa") is None


# ---------------------------------------------------------------- new profile kinds

def level(profile_id, pollutant, concentration, index=0):
    from aqi_engine import band_level
    t = table(profile_id, pollutant, index)
    return band_level(round_concentration(concentration, t["decimals"], t["rounding"]), t, AQI[profile_id]["upper_bound"])[0]


@pytest.mark.parametrize("pollutant, concentration, expected", [
    ("pm25", 5, 1), ("pm25", 5.4, 1), ("pm25", 12, 2), ("pm25", 141, 6),  # 24 h means
    ("no2", 30, 3), ("o3", 100, 2), ("o3", 181, 6), ("pm10", 45, 2),
])
def test_eea_eaqi_levels(pollutant, concentration, expected):
    assert level("eea_eaqi", pollutant, concentration) == expected


@pytest.mark.parametrize("pollutant, concentration, expected", [
    ("pm25", 11, 1), ("pm25", 12, 2), ("pm25", 36, 4), ("pm25", 70, 9), ("pm25", 71, 10),
    ("pm10", 100, 9), ("o3", 101, 4), ("no2", 601, 10),
])
def test_uk_daqi_levels(pollutant, concentration, expected):
    assert level("uk_daqi", pollutant, concentration) == expected


def test_uk_daqi_overall_level_and_category():
    engine = FakeEngine({("pm25", 24, None): (36.0, False), ("o3", 8, None): (20.0, False)})  # 20 ppb O3 = 39 ug/m3
    result = engine.compute("uk_daqi")
    assert result["kind"] == "banded" and result["value"] == 4 and result["category"] == "moderate"
    assert result["sub_indices"]["o3"]["value"] == 2 and result["dominant"] == ["pm25"]


@pytest.mark.parametrize("pollutant, concentration, expected", [
    ("pm25", 45, 75),    # 51 + 49 / 29 * 14 = 74.7
    ("pm10", 300, 250),  # 201 + 99 / 99 * 49
    ("co", 1.5, 73),     # 51 + 49 / 0.9 * 0.4 = 72.8
    ("no2", 40, 50), ("o3", 100, 100),
])
def test_india_naqi(pollutant, concentration, expected):
    assert sub_index("india_naqi", pollutant, concentration) == (expected, False)


def test_india_needs_three_pollutants_including_particles():
    assert FakeEngine({("no2", 24, None): (10.0, False), ("o3", 8, None): (20.0, False),
                       ("co", 8, None): (1.0, False)}).compute("india_naqi") is None
    assert FakeEngine({("pm25", 24, None): (45.0, False), ("no2", 24, None): (10.0, False)}).compute("india_naqi") is None
    result = FakeEngine({("pm25", 24, None): (45.0, False), ("no2", 24, None): (10.0, False),
                         ("o3", 8, None): (20.0, False)}).compute("india_naqi")
    assert result["value"] == 75 and result["category"] == "satisfactory"


@pytest.mark.parametrize("pollutant, concentration, expected", [
    ("pm25", 15, 50), ("pm25", 16, 51), ("pm25", 35, 100), ("pm25", 36, 101), ("pm10", 81, 101),
    ("o3", 0.100, 124),  # 101 + 149 / 0.059 * 0.009 = 123.7
    ("co", 9.0, 100), ("no2", 0.0305, 50),  # truncated to 0.030
])
def test_korea_cai(pollutant, concentration, expected):
    assert sub_index("korea_cai", pollutant, concentration) == (expected, False)


def test_korea_cai_multi_pollutant_bonus():
    # PM2.5 80 ug/m3 -> very unhealthy (251 + 249 / 424 * 4 = 253.3), O3 100 ppb -> unhealthy (124): 2 pollutants, +50
    engine = FakeEngine({("pm25", 24, None): (80.0, False), ("o3", 1, None): (100.0, False), ("no2", 1, None): (10.0, False)})
    result = engine.compute("korea_cai")
    assert result["sub_indices"]["pm25"]["value"] == 253 and result["sub_indices"]["o3"]["value"] == 124
    assert result["bonus"] == 50 and result["value"] == 303 and result["category"] == "very_unhealthy"
    # a single unhealthy pollutant: no bonus
    single = FakeEngine({("pm25", 24, None): (80.0, False), ("o3", 1, None): (20.0, False)}).compute("korea_cai")
    assert single["bonus"] == 0 and single["value"] == 253


def test_canada_aqhi():
    import math
    engine = FakeEngine({("no2", 3, None): (20.0, False), ("o3", 3, None): (30.0, False), ("pm25", 3, None): (10.0, False)})
    result = engine.compute("canada_aqhi")
    expected = 1000 / 10.4 * ((math.exp(0.000871 * 20) - 1) + (math.exp(0.000537 * 30) - 1) + (math.exp(0.000487 * 10) - 1))
    assert expected == pytest.approx(3.72, abs=0.01)
    assert result["kind"] == "additive_risk" and result["value"] == 4 and result["category"] == "moderate"
    assert result["dominant"] == ["no2"]
    high = FakeEngine({("no2", 3, None): (80.0, False), ("o3", 3, None): (90.0, False), ("pm25", 3, None): (150.0, False)}).compute("canada_aqhi")
    assert high["value"] == 19 and high["display"] == "10+" and high["category"] == "very_high"
    low = FakeEngine({("no2", 3, None): (0.0, False), ("o3", 3, None): (0.0, False), ("pm25", 3, None): (0.0, False)}).compute("canada_aqhi")
    assert low["value"] == 1  # the AQHI starts at 1
    assert FakeEngine({("no2", 3, None): (20.0, False)}).compute("canada_aqhi") is None  # every term is needed


@pytest.mark.parametrize("co2, outdoor, category", [
    (900, None, "cat_i"), (970, None, "cat_i"), (971, None, "cat_ii"), (1000, "400", "cat_ii"),
    (950, "400", "cat_i"), (1800, "420", "cat_iv"), (1770, "420", "cat_iii"),
])
def test_co2_en16798_relative_to_outdoor(co2, outdoor, category):
    options = {"outdoor_co2": outdoor} if outdoor else {}  # default outdoor level: 420 ppm
    result = FakeEngine({("co2", None, 10): (co2, False)}).compute("co2_en16798", options)
    assert result["pollutant"] == "co2" and result["category"] == category and result["unit"] == "ppm"


@pytest.mark.parametrize("co2, category", [(999, "harmless"), (1000, "elevated"), (2000, "unacceptable")])
def test_co2_uba(co2, category):
    assert FakeEngine({("co2", None, 10): (co2, False)}).compute("co2_uba")["category"] == category
