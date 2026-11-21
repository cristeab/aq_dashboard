#!/usr/bin/env python3
"""
Configurable air quality index engine.

The profiles (profiles/aqi/*.json, see profile_loader.py) define for each
pollutant the averaging period, the concentration unit and rounding and the
breakpoint tables, plus the index categories with their descriptions and
health recommendations. Two kinds of profiles are supported:

- "index": piecewise linear sub-index per pollutant (US EPA, CAQI, China...),
  the index is the highest sub-index;
- "banded": the concentration thresholds of each pollutant give a level
  (e.g. EEA EAQI 1-6, UK DAQI 1-10), the index is the highest level;
- "additive_risk": sum of the health risks of several pollutants (Canada AQHI);
- "concentration": the (averaged) concentration of a selectable pollutant,
  classified with concentration levels (e.g. WHO guideline levels, CO2 classes).

The PM2.5 concentrations can be corrected for humidity (pm_correction.py)
before any averaging or lookup.
"""

import math
from typing import Dict, Optional, Tuple

from pm_correction import DEFAULT_PM25_CORRECTION, PM25_CORRECTIONS
from pollutant_history import POLLUTANT_SOURCES, PollutantHistory, compute_average
from profile_loader import load_profiles

MOLECULAR_WEIGHTS = {"o3": 47.997, "no2": 46.0055, "co": 28.010}
MOLAR_VOLUME_0C_L = 22.41396954  # ideal gas at 273.15 K, 101.325 kPa
UNIT_LABELS = {"ug/m3": "µg/m³", "mg/m3": "mg/m³", "ppb": "ppb", "ppm": "ppm"}
EPSILON = 1e-9


def convert_concentration(value: float, pollutant: str, from_unit: str, to_unit: str, temperature_c: float) -> float:
    """Converts between ppb, ppm, µg/m³ and mg/m³ (gases at 101.325 kPa and the given temperature)."""
    if from_unit == to_unit:
        return value
    molar_volume = MOLAR_VOLUME_0C_L * (273.15 + temperature_c) / 273.15
    factor = {"ppb": 1.0, "ppm": 1000.0, "ug/m3": None, "mg/m3": None}
    # to µg/m³
    if from_unit in ("ppb", "ppm"):
        ug = value * factor[from_unit] * MOLECULAR_WEIGHTS[pollutant] / molar_volume
    else:
        ug = value * (1000.0 if from_unit == "mg/m3" else 1.0)
    # from µg/m³
    if to_unit in ("ppb", "ppm"):
        return ug * molar_volume / MOLECULAR_WEIGHTS[pollutant] / factor[to_unit]
    return ug / (1000.0 if to_unit == "mg/m3" else 1.0)


def round_concentration(value: float, decimals: int, mode: str) -> float:
    scale = 10 ** decimals
    if mode == "truncate":
        # epsilon: 0.07 is stored as 0.06999... and must not be truncated to 0.069
        return math.floor(value * scale + EPSILON) / scale
    return math.floor(value * scale + 0.5) / scale


def round_index(value: float, mode: str) -> int:
    if mode == "ceil":
        return int(math.ceil(value - EPSILON))
    if mode == "floor":
        return int(math.floor(value + EPSILON))
    return int(math.floor(value + 0.5))


def breakpoint_index(concentration: float, table: Dict) -> Optional[Tuple[float, bool]]:
    """Piecewise linear interpolation. Returns (index, above_range) or None
    when the concentration is outside the range where the table applies."""
    segments = table["breakpoints"]
    c = concentration
    if c < segments[0][0]:
        if table.get("below_range", "clamp") == "not_applicable":
            return None
        c = segments[0][0]
    for c_low, c_high, i_low, i_high in segments:
        if c <= c_high:
            c = max(c, c_low)  # between two segments (e.g. 9.05 with a 9.0/9.1 gap): lower end of the next one
            return (i_high - i_low) / (c_high - c_low) * (c - c_low) + i_low, False
    if table.get("above_range", "cap") == "not_applicable":
        return None
    return segments[-1][3], True


def band_level(concentration: float, table: Dict, upper_bound: str) -> Tuple[int, bool]:
    """Banded indices (e.g. EEA EAQI, UK DAQI): level 1 up to the first
    threshold, level 2 up to the second... (level, above the last threshold)."""
    thresholds = table["thresholds"]
    for level, upper in enumerate(thresholds, start=1):
        if concentration < upper or (upper_bound == "inclusive" and concentration == upper):
            return level, False
    return len(thresholds) + 1, False


def categorize(value: float, categories, upper_bound: str) -> Dict:
    for category in categories:
        if "to" not in category:
            return category
        if value < category["to"] or (upper_bound == "inclusive" and value == category["to"]):
            return category
    return categories[-1]


class AqiEngine:
    def __init__(self, storage, logger=None, profiles: Dict[str, Dict] = None, kind: str = "aqi",
                 history: Optional[PollutantHistory] = None):
        """kind: "aqi" or "co2" (indoor CO2 classification profiles). An engine
        may share the history of another one (refreshed by its owner)."""
        self.profiles = profiles if profiles is not None else load_profiles(kind, logger=logger)
        self.history = history if history is not None else PollutantHistory(storage)

    def refresh(self, now_ms: Optional[int] = None):
        self.history.refresh(now_ms)

    def compute(self, profile_id: str, options: Optional[Dict] = None,
                pm25_correction: str = DEFAULT_PM25_CORRECTION) -> Optional[Dict]:
        """Computes the index with the given profile from the data loaded by the
        last refresh(). Returns None if there is not enough pollutant data."""
        profile = self.profiles[profile_id]
        self._correction = PM25_CORRECTIONS.get(pm25_correction)
        options = options or {}
        if profile["kind"] == "concentration":
            result = self._compute_concentration(profile, options)
        elif profile["kind"] == "additive_risk":
            result = self._compute_additive_risk(profile)
        else:
            result = self._compute_index(profile)
        if result is not None:
            result["pm25_correction"] = pm25_correction if self._correction else "none"
        return result

    def _averaged(self, profile: Dict, pollutant: str, spec: Dict):
        """(average in the unit and rounding of the spec, Average) or None."""
        correction = self._correction if pollutant == "pm25" else None
        average = compute_average(self.history, pollutant, spec["averaging"], correction)
        if average is None:
            return None
        stored_unit = POLLUTANT_SOURCES[pollutant][2]
        value = convert_concentration(average.value, pollutant, stored_unit, spec["unit"],
                                      profile.get("gas_reference_temperature_c", 25))
        return round_concentration(value, spec["decimals"], spec["rounding"]), average

    @staticmethod
    def _sub_index_entry(value, above, concentration, table, average) -> Dict:
        return {
            "value": value,
            "above_scale": above,
            "concentration": concentration,
            "unit": UNIT_LABELS[table["unit"]],
            "averaging": table["averaging"],
            "provisional": average.provisional,
            "coverage": round(average.coverage, 3),
            "corrected": average.corrected,
        }

    def _compute_index(self, profile: Dict) -> Optional[Dict]:
        """Piecewise linear ("index") or banded ("banded") sub-indices, the index is the highest one."""
        banded = profile["kind"] == "banded"
        sub_indices = {}
        for pollutant, tables in profile["pollutants"].items():
            best = None
            for table in tables:
                averaged = self._averaged(profile, pollutant, table)
                if averaged is None:
                    continue
                concentration, average = averaged
                if banded:
                    result = band_level(concentration, table, profile["upper_bound"])
                else:
                    result = breakpoint_index(concentration, table)
                if result is None:
                    continue
                index = result[0] if banded else round_index(result[0], profile["index_rounding"])
                if best is None or index > best["value"]:
                    best = self._sub_index_entry(index, result[1], concentration, table, average)
            if best is not None:
                category = profile["categories"][-1] if best["above_scale"] else \
                    categorize(best["value"], profile["categories"], profile["upper_bound"])
                best["category"] = category["id"]
                best["display"] = profile["above_scale_display"] if best["above_scale"] else str(best["value"])
                sub_indices[pollutant] = best
        if not sub_indices or not self._requirements_met(profile, sub_indices):
            return None

        value = max(s["value"] for s in sub_indices.values())
        leaders = [p for p, s in sub_indices.items() if s["value"] == value]
        above_scale = any(sub_indices[p]["above_scale"] for p in leaders)
        value, bonus = self._multi_pollutant_bonus(profile, sub_indices, value)
        dominant = leaders if value > profile.get("dominant_pollutant_min_index", 0) else []
        category = profile["categories"][-1] if above_scale else \
            categorize(value, profile["categories"], profile["upper_bound"])
        return {
            "profile": profile["id"],
            "kind": profile["kind"],
            "value": value,
            "display": profile["above_scale_display"] if above_scale else str(value),
            "above_scale": above_scale,
            "category": category["id"],
            "dominant": dominant,
            "bonus": bonus,
            # the index is provisional when its leading pollutant(s) lack data for the averaging period
            "provisional": any(sub_indices[p]["provisional"] for p in leaders),
            "coverage": min(sub_indices[p]["coverage"] for p in leaders),
            "sub_indices": sub_indices,
        }

    @staticmethod
    def _requirements_met(profile: Dict, sub_indices: Dict) -> bool:
        """E.g. India: at least 3 pollutants, one of them PM2.5 or PM10."""
        requirements = profile.get("requirements")
        if not requirements:
            return True
        if len(sub_indices) < requirements.get("min_pollutants", 0):
            return False
        one_of = requirements.get("one_of")
        return not one_of or any(p in sub_indices for p in one_of)

    @staticmethod
    def _multi_pollutant_bonus(profile: Dict, sub_indices: Dict, value: int) -> Tuple[int, int]:
        """E.g. Korea CAI: when 2 (3 or more) pollutants are "unhealthy" or worse,
        50 (75) is added to the highest sub-index."""
        rule = profile.get("multi_pollutant_bonus")
        if not rule:
            return value, 0
        order = [c["id"] for c in profile["categories"]]
        threshold = order.index(rule["from_category"])
        count = sum(1 for s in sub_indices.values() if order.index(s["category"]) >= threshold)
        bonus = 0
        for minimum_count, points in rule["bonus"]:
            if count >= minimum_count:
                bonus = points
        return min(value + bonus, profile["scale"]["max"]), bonus

    def _compute_additive_risk(self, profile: Dict) -> Optional[Dict]:
        """Risk based index, e.g. Canada AQHI = 1000/10.4 * sum(exp(beta * C) - 1)."""
        terms = {}
        for pollutant, term in profile["terms"].items():
            averaged = self._averaged(profile, pollutant, term)
            if averaged is None:
                return None  # every term is needed
            concentration, average = averaged
            contribution = profile["scale_factor"] * (math.exp(term["beta"] * concentration) - 1.0)
            entry = self._sub_index_entry(round(contribution, 1), False, concentration, term, average)
            entry["display"] = f"{contribution:.1f}"
            entry["category"] = categorize(contribution, profile["categories"], profile["upper_bound"])["id"]
            terms[pollutant] = entry
        raw = profile["scale_factor"] * sum(math.exp(profile["terms"][p]["beta"] * t["concentration"]) - 1.0
                                            for p, t in terms.items())
        value = max(profile.get("index_min", 0), round_index(raw, profile["index_rounding"]))
        above_scale = value > profile["index_max"]
        category = profile["categories"][-1] if above_scale else \
            categorize(value, profile["categories"], profile["upper_bound"])
        leaders = [max(terms, key=lambda p: terms[p]["value"])]
        return {
            "profile": profile["id"],
            "kind": "additive_risk",
            "value": value,
            "display": profile["above_scale_display"] if above_scale else str(value),
            "above_scale": above_scale,
            "category": category["id"],
            "dominant": leaders,
            "bonus": 0,
            "provisional": any(t["provisional"] for t in terms.values()),
            "coverage": min(t["coverage"] for t in terms.values()),
            "sub_indices": terms,
        }

    @staticmethod
    def concentration_levels(profile: Dict, pollutant: str, options: Dict):
        """[(category id, upper limit or None)], shifted by the value of an
        option when the levels are relative (e.g. CO2 above the outdoor level)."""
        spec = profile["pollutants"][pollutant]
        offset = 0.0
        option_id = spec.get("levels_offset_option")
        if option_id:
            option = next(o for o in profile["options"] if o["id"] == option_id)
            offset = float(options.get(option_id, option["default"]))
        return [(category, None if upper is None else upper + offset) for category, upper in spec["levels"]]

    def _compute_concentration(self, profile: Dict, options: Dict) -> Optional[Dict]:
        pollutants = list(profile["pollutants"])
        option = next((o for o in profile.get("options", []) if o["id"] == "pollutant"), None)
        selected = pollutants[0]
        if option is not None:
            selected = options.get("pollutant", option["default"])
            if selected not in option["values"]:
                selected = option["default"]
        categories = {c["id"]: c for c in profile["categories"]}
        sub_indices = {}
        for pollutant, spec in profile["pollutants"].items():
            averaged = self._averaged(profile, pollutant, spec)
            if averaged is None:
                continue
            concentration, average = averaged
            levels = self.concentration_levels(profile, pollutant, options)
            category_id = levels[-1][0]
            for level_category, upper in levels[:-1]:
                if concentration < upper or (profile["upper_bound"] == "inclusive" and concentration == upper):
                    category_id = level_category
                    break
            entry = self._sub_index_entry(concentration, concentration > spec["scale"]["max"], concentration, spec, average)
            entry["display"] = f"{concentration:.{spec['decimals']}f}"
            entry["category"] = categories[category_id]["id"]
            entry["levels"] = levels
            sub_indices[pollutant] = entry
        if selected not in sub_indices:
            return None
        main = sub_indices[selected]
        return {
            "profile": profile["id"],
            "kind": "concentration",
            "pollutant": selected,
            "value": main["value"],
            "display": main["display"],
            "unit": main["unit"],
            "above_scale": main["above_scale"],
            "category": main["category"],
            "levels": main["levels"],
            "dominant": [selected],
            "bonus": 0,
            "provisional": main["provisional"],
            "coverage": main["coverage"],
            "sub_indices": sub_indices,
        }
