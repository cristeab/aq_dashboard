#!/usr/bin/env python3
"""
Environmental noise engine: equivalent continuous sound level (LAeq, energy
average of the measured levels) over the averaging period of the selected
profile (profiles/noise/*.json), classified with absolute levels (e.g.
occupational exposure action values) or with levels relative to a guideline
limit that depends on the room and on the time of the day (WHO guidelines).
"""

import math
from datetime import datetime
from typing import Dict, Optional

from pollutant_history import compute_energy_average
from profile_loader import load_profiles


def _minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def period_at(periods, moment: datetime) -> Dict:
    """Guideline period (e.g. day 07:00-23:00, night 23:00-07:00) of a local time."""
    now = moment.hour * 60 + moment.minute
    for period in periods:
        start, end = _minutes(period["from"]), _minutes(period["to"])
        if (start <= now < end) if start < end else (now >= start or now < end):
            return period
    return periods[0]


class NoiseEngine:
    def __init__(self, history, logger=None, profiles: Dict[str, Dict] = None):
        self.profiles = profiles if profiles is not None else load_profiles("noise", logger=logger)
        self.history = history

    @staticmethod
    def options(profile: Dict, selected: Optional[Dict] = None) -> Dict:
        selected = selected or {}
        return {o["id"]: selected.get(o["id"]) if selected.get(o["id"]) in o["values"] else o["default"]
                for o in profile.get("options", [])}

    @staticmethod
    def effective_levels(profile: Dict, options: Dict, moment: datetime):
        """[(category, upper limit)] and the guideline period, if the levels are relative to a limit."""
        limits = profile.get("limits")
        if not limits:
            return [(c, u) for c, u in profile["levels"]], None
        period = period_at(limits["values"][options[limits["option"]]], moment)
        return [(c, None if u is None else u + period["limit"]) for c, u in profile["levels"]], period

    def compute(self, profile_id: str, options: Optional[Dict] = None, moment: Optional[datetime] = None) -> Optional[Dict]:
        """LAeq of the profile from the history loaded by the last refresh of the
        (shared) pollutant history; moment: local time for the guideline period."""
        profile = self.profiles[profile_id]
        options = self.options(profile, options)
        average = compute_energy_average(self.history, "noise", profile["averaging"]["minutes"])
        if average is None:
            return None
        decimals = profile["decimals"]
        laeq = 10.0 * math.log10(average.value) if average.value > 0 else 0.0
        value = math.floor(laeq * 10 ** decimals + 0.5) / 10 ** decimals
        levels, period = self.effective_levels(profile, options, moment or datetime.now())
        categories = {c["id"]: c for c in profile["categories"]}
        category_id = levels[-1][0]
        for level_category, upper in levels[:-1]:
            if value < upper or (profile["upper_bound"] == "inclusive" and value == upper):
                category_id = level_category
                break
        return {
            "profile": profile["id"],
            "value": value,
            "display": f"{value:.{decimals}f}",
            "unit": profile["unit"],
            "category": categories[category_id]["id"],
            "levels": levels,
            "period": period["id"] if period else None,
            "limit": period["limit"] if period else None,
            "averaging": profile["averaging"],
            "provisional": average.provisional,
            "coverage": round(average.coverage, 3),
        }
