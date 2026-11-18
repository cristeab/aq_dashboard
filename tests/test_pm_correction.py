import pytest

from pm_correction import PM25_CORRECTIONS, barkjohn_2021, epa_2022_extended


def test_barkjohn_2021():
    # PM2.5 = 0.524 PA_cf1 - 0.0862 RH + 5.75
    assert barkjohn_2021(20, 50) == pytest.approx(11.92)
    assert barkjohn_2021(0, 0) == pytest.approx(5.75)


@pytest.mark.parametrize("boundary", [30, 50, 210, 260])
def test_extended_correction_is_continuous(boundary):
    for rh in (20, 50, 80):
        assert epa_2022_extended(boundary - 1e-9, rh) == pytest.approx(epa_2022_extended(boundary, rh), abs=1e-6)


def test_extended_correction_equals_barkjohn_at_low_concentrations():
    for x in (0, 5, 15, 29.9):
        assert epa_2022_extended(x, 60) == pytest.approx(barkjohn_2021(x, 60))


def test_settings_values():
    assert PM25_CORRECTIONS["none"] is None and set(PM25_CORRECTIONS) == {"none", "barkjohn_2021", "epa_2022_extended"}
