#!/usr/bin/env python3
"""
Loads and validates the index profiles (JSON files) used by the AQI engine
(profiles/aqi) and by the thermal comfort engine (profiles/comfort).

A profile may extend another one with "extends": "<profile id>": the keys of
the child replace the keys of the parent (shallow merge), so that e.g. a
variant only needs to redefine its "pollutants".

Texts are dictionaries {language code: text}; English ("en") is mandatory and
is the fallback for the other languages.
"""

import json
import math
import os
import re
from typing import Dict, List

PROFILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles")

# Pollutants measured by the sensors and the units their concentrations may be expressed in
POLLUTANT_UNITS = {
    "pm25": {"ug/m3"},
    "pm10": {"ug/m3"},
    "o3": {"ug/m3", "mg/m3", "ppb", "ppm"},
    "no2": {"ug/m3", "mg/m3", "ppb", "ppm"},
    "co": {"ug/m3", "mg/m3", "ppb", "ppm"},
    "co2": {"ppm"},
}
COMFORT_FORMULAS = {"thom_di", "thom_thi_f", "humidex", "heat_index_c", "pmv_iso7730"}
# options that a comfort formula needs (numeric values)
FORMULA_OPTIONS = {"pmv_iso7730": {"clo", "met", "air_speed"}}
# Averaging periods cannot exceed the history kept by PollutantHistory
MAX_AVERAGING_HOURS = 24
_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class ProfileError(ValueError):
    pass


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class _Validator:
    def __init__(self, profile: Dict, source: str):
        self.p = profile
        self.source = source

    def fail(self, message: str):
        raise ProfileError(f"{self.source}: {message}")

    def require(self, obj: Dict, key: str, where: str = "profile"):
        if key not in obj:
            self.fail(f"missing '{key}' in {where}")
        return obj[key]

    def text(self, obj: Dict, key: str, where: str):
        value = self.require(obj, key, where)
        if not isinstance(value, dict) or not isinstance(value.get("en"), str) or not value["en"].strip():
            self.fail(f"'{key}' in {where} must be a dict of texts with a non-empty 'en' entry")
        for language, text in value.items():
            if not isinstance(text, str):
                self.fail(f"'{key}.{language}' in {where} must be a string")

    def one_of(self, obj: Dict, key: str, allowed, where: str, default=None):
        value = obj.get(key, default)
        if value not in allowed:
            self.fail(f"'{key}' in {where} must be one of {sorted(allowed)}, not {value!r}")
        return value

    def number(self, obj: Dict, key: str, where: str):
        value = self.require(obj, key, where)
        if not _is_number(value):
            self.fail(f"'{key}' in {where} must be a number")
        return value

    def scale(self, obj: Dict, where: str):
        scale = self.require(obj, "scale", where)
        if not isinstance(scale, dict):
            self.fail(f"'scale' in {where} must be an object")
        low, high = self.number(scale, "min", f"{where}.scale"), self.number(scale, "max", f"{where}.scale")
        if low >= high:
            self.fail(f"scale min must be lower than max in {where}")
        return low, high

    def common(self):
        p = self.p
        if not isinstance(p.get("id"), str) or not re.match(r"^[a-z0-9_]+$", p["id"]):
            self.fail("'id' must be a lowercase identifier")
        for key in ("name", "short_name", "description"):
            self.text(p, key, "profile")
        if not isinstance(self.require(p, "reference"), str):
            self.fail("'reference' must be a string")
        self.one_of(p, "upper_bound", {"inclusive", "exclusive"}, "profile")
        if "order" in p and not _is_number(p["order"]):
            self.fail("'order' must be a number")
        categories = self.require(p, "categories")
        if not isinstance(categories, list) or not categories:
            self.fail("'categories' must be a non-empty list")
        seen = set()
        for i, category in enumerate(categories):
            where = f"categories[{i}]"
            cid = self.require(category, "id", where)
            if not isinstance(cid, str) or cid in seen:
                self.fail(f"{where}: 'id' must be a unique string")
            seen.add(cid)
            if not _COLOR_RE.match(str(category.get("color", ""))):
                self.fail(f"{where}: 'color' must be '#RRGGBB'")
            # color of the colour-blind safe palette (optional, the official color otherwise)
            if "cvd_color" in category and not _COLOR_RE.match(str(category["cvd_color"])):
                self.fail(f"{where}: 'cvd_color' must be '#RRGGBB'")
            for key in ("name", "description", "recommendation"):
                self.text(category, key, where)
        return categories

    def ordered_bounds(self, categories: List[Dict], last_open: bool, scale_max=None):
        previous = -math.inf
        for i, category in enumerate(categories):
            is_last = i == len(categories) - 1
            if is_last and last_open:
                if "to" in category:
                    self.fail(f"categories[{i}]: the last category is open ended and must not have 'to'")
                continue
            to = self.number(category, "to", f"categories[{i}]")
            if to <= previous:
                self.fail(f"categories[{i}]: 'to' values must be increasing")
            previous = to
        if scale_max is not None and previous != scale_max:
            self.fail(f"the last category must end at the scale maximum ({scale_max})")

    def averaging(self, spec, where: str):
        if not isinstance(spec, dict):
            self.fail(f"'averaging' in {where} must be an object")
        kind = self.one_of(spec, "type", {"mean", "nowcast"}, f"{where}.averaging")
        if kind == "mean":
            if ("hours" in spec) == ("minutes" in spec):
                self.fail(f"{where}.averaging: a mean needs either 'hours' or 'minutes'")
            if "hours" in spec:
                hours = spec["hours"]
                if not isinstance(hours, int) or not 1 <= hours <= MAX_AVERAGING_HOURS:
                    self.fail(f"{where}.averaging: 'hours' must be an integer between 1 and {MAX_AVERAGING_HOURS}")
            else:
                minutes = spec["minutes"]
                if not isinstance(minutes, int) or not 1 <= minutes <= 60:
                    self.fail(f"{where}.averaging: 'minutes' must be an integer between 1 and 60")
        else:
            hours = spec.get("hours")
            if not isinstance(hours, int) or not 3 <= hours <= MAX_AVERAGING_HOURS:
                self.fail(f"{where}.averaging: NowCast 'hours' must be an integer between 3 and {MAX_AVERAGING_HOURS}")
            weight = spec.get("min_weight")
            if not _is_number(weight) or not 0 < weight <= 1:
                self.fail(f"{where}.averaging: NowCast 'min_weight' must be in ]0, 1]")

    def concentration_format(self, table: Dict, pollutant: str, where: str):
        self.averaging(self.require(table, "averaging", where), where)
        unit = self.require(table, "unit", where)
        if unit not in POLLUTANT_UNITS[pollutant]:
            self.fail(f"{where}: unit {unit!r} is not valid for {pollutant} ({sorted(POLLUTANT_UNITS[pollutant])})")
        decimals = self.require(table, "decimals", where)
        if not isinstance(decimals, int) or not 0 <= decimals <= 4:
            self.fail(f"{where}: 'decimals' must be an integer between 0 and 4")
        self.one_of(table, "rounding", {"truncate", "round"}, where)

    def pollutant_keys(self, pollutants):
        if not isinstance(pollutants, dict) or not pollutants:
            self.fail("'pollutants' must be a non-empty object")
        for pollutant in pollutants:
            if pollutant not in POLLUTANT_UNITS:
                self.fail(f"unknown pollutant {pollutant!r} (known: {sorted(POLLUTANT_UNITS)})")

    def options(self, numeric_ids=()):
        """Validates the "options" of a profile; returns {option id: option}."""
        options = self.p.get("options", [])
        if not isinstance(options, list):
            self.fail("'options' must be a list")
        declared = {}
        for i, option in enumerate(options):
            where = f"options[{i}]"
            option_id = self.require(option, "id", where)
            if not isinstance(option_id, str) or option_id in declared:
                self.fail(f"{where}: 'id' must be a unique string")
            values = self.require(option, "values", where)
            if (not isinstance(values, list) or not values or not all(isinstance(v, str) for v in values)
                    or option.get("default") not in values):
                self.fail(f"{where}: 'values' must be a non-empty list of strings containing 'default'")
            self.text(option, "label", where)
            for value, texts in option.get("value_labels", {}).items():
                if value not in values:
                    self.fail(f"{where}: value_labels has an unknown value {value!r}")
                self.text(option["value_labels"], value, where)
            if option_id in numeric_ids:
                try:  # "auto" values are computed by the engine (e.g. the clothing of the season)
                    [float(v) for v in values if not v.startswith("auto")]
                except ValueError:
                    self.fail(f"{where}: the values of option {option_id!r} must be numbers")
            declared[option_id] = option
        return declared

    def threshold_tables(self, tables, pollutant, levels_expected):
        for t, table in enumerate(tables):
            where = f"pollutants.{pollutant}[{t}]"
            self.concentration_format(table, pollutant, where)
            thresholds = self.require(table, "thresholds", where)
            if (not isinstance(thresholds, list) or not thresholds or not all(_is_number(v) for v in thresholds)
                    or any(b <= a for a, b in zip(thresholds, thresholds[1:]))):
                self.fail(f"{where}: 'thresholds' must be increasing numbers")
            if len(thresholds) + 1 != levels_expected:
                self.fail(f"{where}: {len(thresholds)} thresholds give {len(thresholds) + 1} levels, "
                          f"the scale has {levels_expected}")

    def index_profile(self):
        p = self.p
        categories = self.common()
        banded = p["kind"] == "banded"
        if not banded:
            self.one_of(p, "index_rounding", {"nearest", "ceil", "floor"}, "profile")
        self.number(p, "gas_reference_temperature_c", "profile")
        self.number(p, "dominant_pollutant_min_index", "profile")
        if not isinstance(self.require(p, "above_scale_display"), str):
            self.fail("'above_scale_display' must be a string")
        scale_min, scale_max = self.scale(p, "profile")
        self.ordered_bounds(categories, last_open=False, scale_max=scale_max)
        category_ids = [c["id"] for c in categories]
        bonus = p.get("multi_pollutant_bonus")
        if bonus is not None:
            if bonus.get("from_category") not in category_ids or not isinstance(bonus.get("bonus"), list) or not all(
                    isinstance(b, list) and len(b) == 2 and isinstance(b[0], int) and _is_number(b[1]) for b in bonus["bonus"]):
                self.fail("'multi_pollutant_bonus' needs 'from_category' and 'bonus': [[pollutant count, points], ...]")
        requirements = p.get("requirements")
        if requirements is not None and (not isinstance(requirements.get("min_pollutants", 0), int)
                                         or not set(requirements.get("one_of", [])) <= set(POLLUTANT_UNITS)):
            self.fail("'requirements' needs an integer 'min_pollutants' and known pollutants in 'one_of'")
        pollutants = self.require(p, "pollutants")
        self.pollutant_keys(pollutants)
        if banded:
            if scale_min != 0 or not float(scale_max).is_integer():
                self.fail("the scale of a banded profile must go from 0 to the number of levels")
            colors = p.get("level_colors")
            if colors is not None and (len(colors) != scale_max or not all(_COLOR_RE.match(str(c)) for c in colors)):
                self.fail("'level_colors' must have one '#RRGGBB' color per level")
            for pollutant, tables in pollutants.items():
                if not isinstance(tables, list) or not tables:
                    self.fail(f"pollutants.{pollutant} must be a non-empty list of threshold tables")
                self.threshold_tables(tables, pollutant, int(scale_max))
            return
        for pollutant, tables in pollutants.items():
            if not isinstance(tables, list) or not tables:
                self.fail(f"pollutants.{pollutant} must be a non-empty list of breakpoint tables")
            for t, table in enumerate(tables):
                where = f"pollutants.{pollutant}[{t}]"
                self.concentration_format(table, pollutant, where)
                self.one_of(table, "below_range", {"clamp", "not_applicable"}, where, default="clamp")
                self.one_of(table, "above_range", {"cap", "not_applicable"}, where, default="cap")
                if "note" in table:
                    self.text(table, "note", where)
                breakpoints = self.require(table, "breakpoints", where)
                if not isinstance(breakpoints, list) or not breakpoints:
                    self.fail(f"{where}: 'breakpoints' must be a non-empty list")
                previous = None
                for b, segment in enumerate(breakpoints):
                    if (not isinstance(segment, list) or len(segment) != 4 or not all(_is_number(v) for v in segment)):
                        self.fail(f"{where}.breakpoints[{b}] must be [C_low, C_high, I_low, I_high]")
                    c_low, c_high, i_low, i_high = segment
                    if c_low >= c_high or i_low >= i_high:
                        self.fail(f"{where}.breakpoints[{b}]: low values must be lower than high values")
                    if previous is not None and (c_low < previous[1] or i_low < previous[3]):
                        self.fail(f"{where}.breakpoints[{b}] overlaps the previous segment")
                    previous = segment

    def additive_risk_profile(self):
        p = self.p
        categories = self.common()
        self.one_of(p, "index_rounding", {"nearest", "ceil", "floor"}, "profile")
        for key in ("gas_reference_temperature_c", "scale_factor", "index_min", "index_max"):
            self.number(p, key, "profile")
        if not isinstance(self.require(p, "above_scale_display"), str):
            self.fail("'above_scale_display' must be a string")
        _, scale_max = self.scale(p, "profile")
        self.ordered_bounds(categories, last_open=False, scale_max=scale_max)
        terms = self.require(p, "terms")
        self.pollutant_keys(terms)
        for pollutant, term in terms.items():
            self.concentration_format(term, pollutant, f"terms.{pollutant}")
            self.number(term, "beta", f"terms.{pollutant}")

    def concentration_profile(self):
        p = self.p
        categories = self.common()
        category_ids = {c["id"] for c in categories}
        self.number(p, "gas_reference_temperature_c", "profile")
        pollutants = self.require(p, "pollutants")
        self.pollutant_keys(pollutants)
        for pollutant, spec in pollutants.items():
            where = f"pollutants.{pollutant}"
            self.concentration_format(spec, pollutant, where)
            self.scale(spec, where)
            levels = self.require(spec, "levels", where)
            if not isinstance(levels, list) or not levels:
                self.fail(f"{where}: 'levels' must be a non-empty list")
            previous = -math.inf
            for i, level in enumerate(levels):
                if not isinstance(level, list) or len(level) != 2 or level[0] not in category_ids:
                    self.fail(f"{where}.levels[{i}] must be [category id, upper limit]")
                is_last = i == len(levels) - 1
                if is_last:
                    if level[1] is not None:
                        self.fail(f"{where}.levels[{i}]: the last level must be open ended (null)")
                elif not _is_number(level[1]) or level[1] <= previous:
                    self.fail(f"{where}.levels[{i}]: upper limits must be increasing numbers")
                else:
                    previous = level[1]
        offset_options = {spec["levels_offset_option"] for spec in pollutants.values() if "levels_offset_option" in spec}
        options = self.options(numeric_ids=offset_options)
        if not offset_options <= set(options):
            self.fail(f"unknown 'levels_offset_option' {sorted(offset_options - set(options))}")
        if "pollutant" in options and not set(options["pollutant"]["values"]) <= set(pollutants):
            self.fail("every selectable pollutant must be defined in 'pollutants'")
        if len(pollutants) > 1 and "pollutant" not in options:
            self.fail("a concentration profile of several pollutants needs a 'pollutant' option")

    def noise_profile(self):
        """Equivalent sound level (LAeq) over an averaging period, classified with
        absolute levels, or with levels relative to a guideline limit that may
        depend on an option (e.g. the room) and on the time of the day."""
        p = self.p
        categories = self.common()
        category_ids = {c["id"] for c in categories}
        averaging = self.require(p, "averaging")
        minutes = averaging.get("minutes") if isinstance(averaging, dict) else None
        if averaging.get("type") != "leq" or not isinstance(minutes, int) or not 1 <= minutes <= MAX_AVERAGING_HOURS * 60:
            self.fail(f"'averaging' must be {{\"type\": \"leq\", \"minutes\": 1..{MAX_AVERAGING_HOURS * 60}}}")
        if not isinstance(self.require(p, "unit"), str):
            self.fail("'unit' must be a string")
        decimals = self.require(p, "decimals")
        if not isinstance(decimals, int) or not 0 <= decimals <= 2:
            self.fail("'decimals' must be an integer between 0 and 2")
        self.scale(p, "profile")
        options = self.options()
        levels = self.require(p, "levels")
        previous = -math.inf
        for i, level in enumerate(levels if isinstance(levels, list) else []):
            if not isinstance(level, list) or len(level) != 2 or level[0] not in category_ids:
                self.fail(f"levels[{i}] must be [category id, upper limit]")
            if i == len(levels) - 1:
                if level[1] is not None:
                    self.fail("the last level must be open ended (null)")
            elif not _is_number(level[1]) or level[1] <= previous:
                self.fail(f"levels[{i}]: upper limits must be increasing numbers")
            else:
                previous = level[1]
        if not isinstance(levels, list) or len(levels) < 2:
            self.fail("'levels' must list at least two levels")
        limits = p.get("limits")
        if limits is not None:
            option_id = limits.get("option")
            if option_id not in options:
                self.fail("'limits.option' must be the id of an option")
            periods_by_value = limits.get("values", {})
            if set(periods_by_value) != set(options[option_id]["values"]):
                self.fail("'limits.values' must give the periods of every value of the option")
            for value, periods in periods_by_value.items():
                if not isinstance(periods, list) or not periods:
                    self.fail(f"limits.values.{value} must be a non-empty list of periods")
                for period in periods:
                    if (not re.match(r"^([01]\d|2[0-4]):[0-5]\d$", str(period.get("from", "")))
                            or not re.match(r"^([01]\d|2[0-4]):[0-5]\d$", str(period.get("to", "")))
                            or not _is_number(period.get("limit")) or period.get("id") not in ("day", "evening", "night")):
                        self.fail(f"limits.values.{value}: a period is {{id: day|evening|night, from: HH:MM, to: HH:MM, limit}}")

    def comfort_profile(self):
        p = self.p
        categories = self.common()
        self.one_of(p, "formula", COMFORT_FORMULAS, "profile")
        if not isinstance(self.require(p, "unit"), str):
            self.fail("'unit' must be a string")
        decimals = self.require(p, "decimals")
        if not isinstance(decimals, int) or not 0 <= decimals <= 3:
            self.fail("'decimals' must be an integer between 0 and 3")
        self.scale(p, "profile")
        self.ordered_bounds(categories, last_open=True)
        if p.get("neutral_category") not in {c["id"] for c in categories}:
            self.fail("'neutral_category' must be the id of the category of thermal neutrality (the cold side is before it)")
        required = FORMULA_OPTIONS.get(p["formula"], set())
        options = self.options(numeric_ids=required)
        if not required <= set(options):
            self.fail(f"formula {p['formula']} needs the options {sorted(required)}")


def _read_json(path: str) -> Dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise ProfileError(f"{path}: cannot read profile: {e}") from e
    if not isinstance(data, dict):
        raise ProfileError(f"{path}: a profile must be a JSON object")
    return data


def _resolve(profile_id: str, raw: Dict[str, Dict], paths: Dict[str, str], chain=()) -> Dict:
    if profile_id in chain:
        raise ProfileError(f"{paths[profile_id]}: circular 'extends' ({' -> '.join(chain + (profile_id,))})")
    data = raw[profile_id]
    parent_id = data.get("extends")
    if parent_id is None:
        return dict(data)
    if parent_id not in raw:
        raise ProfileError(f"{paths[profile_id]}: extends unknown profile {parent_id!r}")
    merged = _resolve(parent_id, raw, paths, chain + (profile_id,))
    merged.update({k: v for k, v in data.items() if k != "extends"})
    return merged


PROFILE_KINDS = ("aqi", "co2", "noise", "comfort")


def load_profiles(kind: str, directory: str = None, logger=None) -> Dict[str, Dict]:
    """Loads all valid profiles of a kind ("aqi", "co2", "noise" or "comfort")
    sorted by their "order" then id. Invalid profiles are skipped (and logged),
    so that a mistake in a user edited file does not stop the dashboard."""
    if kind not in PROFILE_KINDS:
        raise ValueError(f"unknown profile kind {kind!r}")
    directory = directory or os.path.join(PROFILES_DIR, kind)
    raw, paths = {}, {}
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(directory, name)
        try:
            data = _read_json(path)
            profile_id = data.get("id")
            if profile_id != name[:-5]:
                raise ProfileError(f"{path}: 'id' ({profile_id!r}) must match the file name")
            raw[profile_id], paths[profile_id] = data, path
        except ProfileError as e:
            _report(e, logger)

    profiles = {}
    for profile_id in raw:
        try:
            profile = _resolve(profile_id, raw, paths)
            validator = _Validator(profile, paths[profile_id])
            if kind == "comfort":
                validator.comfort_profile()
            elif kind == "noise":
                validator.noise_profile()
            elif kind == "co2":
                # indoor CO2 classification: concentration profiles of CO2 only
                if profile.get("kind") != "concentration" or set(profile.get("pollutants", {})) != {"co2"}:
                    validator.fail("a CO2 profile must be a concentration profile of co2 only")
                validator.concentration_profile()
            elif profile.get("kind") in ("index", "banded"):
                validator.index_profile()
            elif profile.get("kind") == "additive_risk":
                validator.additive_risk_profile()
            elif profile.get("kind") == "concentration":
                validator.concentration_profile()
            else:
                validator.fail("'kind' must be 'index', 'banded', 'additive_risk' or 'concentration'")
            profiles[profile_id] = profile
        except ProfileError as e:
            _report(e, logger)
    return dict(sorted(profiles.items(), key=lambda item: (item[1].get("order", 1000), item[0])))


def _report(error: Exception, logger):
    if logger is not None:
        logger.error(f"Skipping invalid profile: {error}")
    else:
        raise error


def localized(texts: Dict[str, str], language: str = "en") -> str:
    return texts.get(language) or texts["en"]
