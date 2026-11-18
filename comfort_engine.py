#!/usr/bin/env python3
"""
Thermal comfort (discomfort index) engine.

The profiles (profiles/comfort/*.json) select a formula computed from the air
temperature and relative humidity, and define its unit, rounding, display
scale and categories with descriptions and recommendations.
"""

import math
from datetime import datetime
from typing import Dict, Optional

from aqi_engine import categorize
from profile_loader import load_profiles


def thom_di(temperature_c: float, relative_humidity: float) -> float:
    """Thom (1959) discomfort index in °C: DI = T - 0.55 (1 - 0.01 RH) (T - 14.5)."""
    return temperature_c - 0.55 * (1.0 - 0.01 * relative_humidity) * (temperature_c - 14.5)


def thom_thi_f(temperature_c: float, relative_humidity: float) -> float:
    """Thom's temperature-humidity index on the Fahrenheit scale:
    THI = T - (0.55 - 0.0055 RH) (T - 58), T in °F."""
    t = temperature_c * 9.0 / 5.0 + 32.0
    return t - (0.55 - 0.0055 * relative_humidity) * (t - 58.0)


def dew_point_c(temperature_c: float, relative_humidity: float) -> float:
    """Magnus formula (WMO coefficients), RH clamped to [1, 100] %."""
    b, c = 17.62, 243.12
    gamma = math.log(min(max(relative_humidity, 1.0), 100.0) / 100.0) + b * temperature_c / (c + temperature_c)
    return c * gamma / (b - gamma)


def humidex(temperature_c: float, relative_humidity: float) -> float:
    """Environment Canada humidex: H = T + 0.5555 (e - 10), with the vapour
    pressure e (hPa) derived from the dew point as in Masterton & Richardson (1979)."""
    dew_point_k = dew_point_c(temperature_c, relative_humidity) + 273.15
    e = 6.11 * math.exp(5417.7530 * (1.0 / 273.16 - 1.0 / dew_point_k))
    return temperature_c + 0.5555 * (e - 10.0)


def heat_index_c(temperature_c: float, relative_humidity: float) -> float:
    """US National Weather Service heat index (°C), computed in °F with the NWS
    algorithm: Steadman's simple formula, and the Rothfusz regression with its
    low and high humidity adjustments when the result is 80 °F or more."""
    t = temperature_c * 9.0 / 5.0 + 32.0
    rh = relative_humidity
    hi = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + rh * 0.094)
    if (hi + t) / 2.0 >= 80.0:
        hi = (-42.379 + 2.04901523 * t + 10.14333127 * rh - 0.22475541 * t * rh - 0.00683783 * t * t
              - 0.05481717 * rh * rh + 0.00122874 * t * t * rh + 0.00085282 * t * rh * rh
              - 0.00000199 * t * t * rh * rh)
        if rh < 13.0 and 80.0 <= t <= 112.0:
            hi -= (13.0 - rh) / 4.0 * math.sqrt((17.0 - abs(t - 95.0)) / 17.0)
        elif rh > 85.0 and 80.0 <= t <= 87.0:
            hi += (rh - 85.0) / 10.0 * (87.0 - t) / 5.0
    return (hi - 32.0) * 5.0 / 9.0


def pmv_ppd(ta: float, tr: float, vr: float, rh: float, met: float, clo: float, wme: float = 0.0):
    """Predicted mean vote and predicted percentage of dissatisfied of ISO 7730
    (identical equations in the 2005 and 2025 editions), computed as in the
    reference program of the standard. ta, tr: air and mean radiant temperature
    (°C), vr: relative air speed (m/s), rh: relative humidity (%), met:
    metabolic rate (met), clo: clothing insulation (clo). Returns (PMV, PPD %)."""
    pa = rh * 10.0 * math.exp(16.6536 - 4030.183 / (ta + 235.0))  # water vapour pressure, Pa
    icl = 0.155 * clo            # clothing insulation, m²K/W
    m = met * 58.15              # metabolic rate, W/m²
    mw = m - wme * 58.15         # internal heat production
    fcl = 1.0 + 1.29 * icl if icl <= 0.078 else 1.05 + 0.645 * icl
    hcf = 12.1 * math.sqrt(vr)   # forced convection
    taa, tra = ta + 273.0, tr + 273.0
    tcla = taa + (35.5 - ta) / (3.5 * icl + 0.1)   # first guess of the clothing temperature
    p1 = icl * fcl
    p2, p3, p4 = p1 * 3.96, p1 * 100.0, p1 * taa
    p5 = 308.7 - 0.028 * mw + p2 * (tra / 100.0) ** 4
    xn, xf = tcla / 100.0, tcla / 50.0
    hc = hcf
    for _ in range(150):
        if abs(xn - xf) <= 0.00015:
            break
        xf = (xf + xn) / 2.0
        hc = max(hcf, 2.38 * abs(100.0 * xf - taa) ** 0.25)
        xn = (p5 + p4 * hc - p2 * xf ** 4) / (100.0 + p3 * hc)
    else:
        raise ArithmeticError("PMV: the clothing temperature does not converge")
    tcl = 100.0 * xn - 273.0
    hl1 = 3.05e-3 * (5733.0 - 6.99 * mw - pa)              # skin diffusion
    hl2 = 0.42 * (mw - 58.15) if mw > 58.15 else 0.0       # sweating
    hl3 = 1.7e-5 * m * (5867.0 - pa)                       # latent respiration
    hl4 = 0.0014 * m * (34.0 - ta)                         # dry respiration
    hl5 = 3.96 * fcl * (xn ** 4 - (tra / 100.0) ** 4)      # radiation
    hl6 = fcl * hc * (tcl - ta)                            # convection
    ts = 0.303 * math.exp(-0.036 * m) + 0.028
    pmv = ts * (mw - hl1 - hl2 - hl3 - hl4 - hl5 - hl6)
    ppd = 100.0 - 95.0 * math.exp(-0.03353 * pmv ** 4 - 0.2179 * pmv ** 2)
    return pmv, ppd


# ISO 7730 clause 4: the PMV model applies within these limits
PMV_LIMITS = {"ta": (10.0, 30.0), "vr": (0.0, 1.0), "met": (0.8, 4.0), "clo": (0.0, 2.0), "pa": (0.0, 2700.0), "pmv": (-2.0, 2.0)}


def seasonal_clo(moment: Optional[datetime] = None, southern_hemisphere: bool = False) -> float:
    """Clothing of the season (ISO 7730 Annex A design values): 0.5 clo in summer
    (May to September in the northern hemisphere, November to March in the
    southern hemisphere), 1.0 clo otherwise."""
    month = (moment or datetime.now()).month
    summer = month in (11, 12, 1, 2, 3) if southern_hemisphere else 5 <= month <= 9
    return 0.5 if summer else 1.0


def pmv_iso7730(temperature_c: float, relative_humidity: float, options: Dict) -> Dict:
    """PMV with the mean radiant temperature taken equal to the air temperature
    (no globe thermometer); PPD as secondary value. Clothing "auto": seasonal_clo()."""
    clo_option = options["clo"]
    if clo_option in ("auto", "auto_south"):
        clo = seasonal_clo(southern_hemisphere=clo_option == "auto_south")
    else:
        clo = float(clo_option)
    met, vr = float(options["met"]), float(options["air_speed"])
    pmv, ppd = pmv_ppd(temperature_c, temperature_c, vr, relative_humidity, met, clo)
    pa = relative_humidity * 10.0 * math.exp(16.6536 - 4030.183 / (temperature_c + 235.0))
    inputs = {"ta": temperature_c, "vr": vr, "met": met, "clo": clo, "pa": pa, "pmv": pmv}
    valid = all(low <= inputs[key] <= high for key, (low, high) in PMV_LIMITS.items())
    return {"value": pmv, "secondary": {"id": "ppd", "value": round(ppd), "unit": "%"}, "valid": valid}


# formulas (temperature °C, relative humidity %) -> value; the ones with options
# return a dict with "value" and optionally "secondary" and "valid"
FORMULAS = {"thom_di": thom_di, "thom_thi_f": thom_thi_f, "humidex": humidex, "heat_index_c": heat_index_c}
OPTION_FORMULAS = {"pmv_iso7730": pmv_iso7730}


class ComfortEngine:
    def __init__(self, logger=None, profiles: Dict[str, Dict] = None):
        self.profiles = profiles if profiles is not None else load_profiles("comfort", logger=logger)

    @staticmethod
    def options(profile: Dict, selected: Optional[Dict] = None) -> Dict:
        """Option values of a profile: the selected ones, or the defaults."""
        selected = selected or {}
        return {o["id"]: selected.get(o["id"], o["default"]) if selected.get(o["id"]) in o["values"] else o["default"]
                for o in profile.get("options", [])}

    def compute(self, profile_id: str, temperature_c: Optional[float], relative_humidity: Optional[float],
                options: Optional[Dict] = None) -> Optional[Dict]:
        if temperature_c is None or relative_humidity is None:
            return None
        profile = self.profiles[profile_id]
        formula = profile["formula"]
        secondary, valid = None, True
        if formula in OPTION_FORMULAS:
            result = OPTION_FORMULAS[formula](temperature_c, relative_humidity, self.options(profile, options))
            raw, secondary, valid = result["value"], result.get("secondary"), result.get("valid", True)
        else:
            raw = FORMULAS[formula](temperature_c, relative_humidity)
        decimals = profile["decimals"]
        value = math.floor(raw * 10 ** decimals + 0.5) / 10 ** decimals
        category = categorize(value, profile["categories"], profile["upper_bound"])
        display = f"{value:+.{decimals}f}" if profile.get("signed") else f"{value:.{decimals}f}"
        return {
            "profile": profile["id"],
            "value": value,
            "display": display.replace("-", "−"),
            "unit": profile["unit"],
            "category": category["id"],
            "secondary": secondary,
            "valid": valid,  # False: outside the validity range of the model
            "above_scale": value > profile["scale"]["max"],
            "below_scale": value < profile["scale"]["min"],
        }
