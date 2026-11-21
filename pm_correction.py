#!/usr/bin/env python3
"""
Humidity corrections of the PM2.5 concentrations measured by Plantower
sensors (PMSA003, PMS5003). These low-cost optical sensors overestimate PM2.5,
more so at high humidity (hygroscopic growth of the particles).

The corrections expect the "CF=1" PM2.5 concentration (average of the two
sensors, in µg/m³) and the relative humidity (in %). They were derived from
PurpleAir sensors, whose humidity sensor sits inside the housing and reads
somewhat lower than the ambient humidity measured here.
"""

from typing import Callable, Dict, Optional


def barkjohn_2021(pm25_cf1: float, relative_humidity: float) -> float:
    """US-wide correction of Barkjohn et al. (2021), Atmos. Meas. Tech. 14, 4617-4637:
    PM2.5 = 0.524 PA_cf1 - 0.0862 RH + 5.75 (fitted on 24 h and valid for 1 h means)."""
    return 0.524 * pm25_cf1 - 0.0862 * relative_humidity + 5.75


def epa_2022_extended(pm25_cf1: float, relative_humidity: float) -> float:
    """Extension of the Barkjohn correction for high (wildfire smoke)
    concentrations used by the US EPA AirNow Fire and Smoke Map (Barkjohn et al.,
    2022): identical below 30 µg/m³, blended piecewise up to 260 µg/m³ and
    quadratic above. The pieces join continuously."""
    x, rh = pm25_cf1, relative_humidity
    if x < 30:
        return 0.524 * x - 0.0862 * rh + 5.75
    if x < 50:
        f = x / 20 - 3 / 2
        return (0.786 * f + 0.524 * (1 - f)) * x - 0.0862 * rh + 5.75
    if x < 210:
        return 0.786 * x - 0.0862 * rh + 5.75
    if x < 260:
        f = x / 50 - 21 / 5
        return ((0.69 * f + 0.786 * (1 - f)) * x - 0.0862 * rh * (1 - f)
                + 2.966 * f + 5.75 * (1 - f) + 8.84e-4 * x ** 2 * f)
    return 2.966 + 0.69 * x + 8.84e-4 * x ** 2


# setting value -> correction (None: the raw CF=1 concentrations are used)
PM25_CORRECTIONS: Dict[str, Optional[Callable[[float, float], float]]] = {
    "none": None,
    "barkjohn_2021": barkjohn_2021,
    "epa_2022_extended": epa_2022_extended,
}
DEFAULT_PM25_CORRECTION = "barkjohn_2021"
