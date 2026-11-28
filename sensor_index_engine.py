"""Classify direct sensor index readings using selectable threshold profiles."""

from typing import Dict, Optional

from aqi_engine import categorize
from profile_loader import load_profiles


class SensorIndexEngine:
    def __init__(self, kind: str, logger=None, profiles: Dict[str, Dict] = None):
        if kind not in ("uv", "voc"):
            raise ValueError(f"unsupported sensor profile kind {kind!r}")
        self.kind = kind
        self.profiles = profiles if profiles is not None else load_profiles(kind, logger=logger)

    def compute(self, profile_id: str, raw_value: Optional[float]) -> Optional[Dict]:
        if raw_value is None:
            return None
        profile = self.profiles[profile_id]
        decimals = profile["decimals"]
        value = round(float(raw_value), decimals)
        category = categorize(value, profile["categories"], profile["upper_bound"])
        return {
            "profile": profile["id"],
            "value": value,
            "display": f"{value:.{decimals}f}",
            "unit": profile["unit"],
            "category": category["id"],
        }
