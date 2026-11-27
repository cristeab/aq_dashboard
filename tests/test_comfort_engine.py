import pytest

from comfort_engine import ComfortEngine, dew_point_c, humidex, thom_di


def test_thom_discomfort_index():
    assert thom_di(30, 60) == pytest.approx(26.59)
    assert thom_di(14.5, 10) == pytest.approx(14.5)  # at 14.5 C humidity has no effect


def test_humidex_environment_canada_table():
    # Environment Canada humidex table: air temperature 30 C, dew point 15 C -> humidex 34
    e_s = lambda t: 6.112 * 2.718281828 ** (17.62 * t / (243.12 + t))
    rh = 100 * e_s(15) / e_s(30)
    assert dew_point_c(30, rh) == pytest.approx(15, abs=0.01)
    assert round(humidex(30, rh)) == 34


@pytest.mark.parametrize("profile, t, rh, category", [
    ("thom_kyle", 18, 50, "comfortable"),      # DI 17.0
    ("thom_kyle", 5, 50, "cold"),              # DI 7.6
    ("thom_kyle", -30, 50, "extremely_cold"),  # DI -17.8
    ("thom_kyle", -45, 50, "glacial"),         # DI -28.6
    ("humidex", 33, 50, "great_discomfort"),   # dew point 21.4 C -> humidex 41.6
    ("humidex", 35, 60, "dangerous"),          # dew point 26.1 C -> humidex 48.6 (EC table: 48)
])
def test_categories(profile, t, rh, category):
    assert ComfortEngine().compute(profile, t, rh)["category"] == category


def test_missing_input():
    assert ComfortEngine().compute("thom_kyle", None, 50) is None


# PMV reference vectors retained from the ISO 7730 PMV method; current profile cites ISO 7730:2025.
# (ta, tr, relative air speed, RH, met, clo) -> (PMV, PPD)
ISO_7730_TABLE_D1 = [
    ((22, 22, 0.1, 60, 1.2, 0.5), (-0.75, 17)), ((27, 27, 0.1, 60, 1.2, 0.5), (0.77, 17)),
    ((27, 27, 0.3, 60, 1.2, 0.5), (0.44, 9)), ((23.5, 25.5, 0.1, 60, 1.2, 0.5), (-0.01, 5)),
    ((23.5, 25.5, 0.3, 60, 1.2, 0.5), (-0.55, 11)), ((19, 19, 0.1, 40, 1.2, 1.0), (-0.60, 13)),
    ((23.5, 23.5, 0.3, 40, 1.2, 1.0), (0.12, 5)), ((23, 21, 0.1, 40, 1.2, 1.0), (0.05, 5)),
    ((23, 21, 0.3, 40, 1.2, 1.0), (-0.16, 6)), ((22, 22, 0.1, 60, 1.6, 0.5), (0.05, 5)),
    ((27, 27, 0.1, 60, 1.6, 0.5), (1.17, 34)), ((27, 27, 0.3, 60, 1.6, 0.5), (0.95, 24)),
]


@pytest.mark.parametrize("inputs, expected", ISO_7730_TABLE_D1)
def test_pmv_ppd_iso7730_table(inputs, expected):
    from comfort_engine import pmv_ppd
    pmv, ppd = pmv_ppd(*inputs)
    assert pmv == pytest.approx(expected[0], abs=0.015) and round(ppd) == pytest.approx(expected[1], abs=1)


@pytest.mark.parametrize("t_f, rh, hi_f", [(80, 40, 80), (90, 50, 95), (90, 70, 106), (100, 40, 109), (86, 90, 105), (94, 55, 106)])
def test_heat_index_nws_chart(t_f, rh, hi_f):
    from comfort_engine import heat_index_c
    assert heat_index_c((t_f - 32) / 1.8, rh) * 1.8 + 32 == pytest.approx(hi_f, abs=1.0)


def test_heat_index_categories():
    engine = ComfortEngine()
    assert engine.compute("nws_heat_index", 22, 50)["category"] == "no_caution"
    assert engine.compute("nws_heat_index", 33, 60)["category"] == "danger"  # HI 39.5 C


def test_pmv_profile_options_and_validity():
    engine = ComfortEngine()
    office = engine.compute("iso7730_pmv", 22, 50)  # defaults: 1.0 clo, 1.2 met, 0.1 m/s
    assert office["display"] == "+0.10" and office["category"] == "neutral_a" and office["valid"]
    assert office["secondary"] == {"id": "ppd", "value": 5, "unit": "%"}
    summer = engine.compute("iso7730_pmv", 22, 50, {"clo": "0.5"})
    assert summer["value"] < -0.7 and summer["category"] == "too_cool" and summer["display"].startswith("−")
    assert engine.compute("iso7730_pmv", 22, 50, {"clo": "9.9"})["display"] == "+0.10"  # invalid option: default
    assert not engine.compute("iso7730_pmv", 33, 60)["valid"]  # above 30 C: outside ISO 7730


def test_dynamic_ui_translation_keys():
    """Keys built at run time in the web interface (maintenance alarms, corrections, states)."""
    import json
    import os
    from dust_sensor_monitor import MESSAGES
    from pm_correction import PM25_CORRECTIONS
    keys = {f"maintenance_{code}" for code in MESSAGES} | {f"maintenance_{code}_action" for code in MESSAGES}
    keys |= {f"pm25_correction_{c}" for c in PM25_CORRECTIONS} | {f"dust_state_{s}" for s in ("learning", "monitoring", "alarm")}
    keys |= {"secondary_ppd", "param_dust_sensors"}
    static = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
    for language in ("en", "ro", "fr", "de"):
        with open(os.path.join(static, f"translations_{language}.json"), encoding="utf-8") as f:
            assert keys <= set(json.load(f)), language
