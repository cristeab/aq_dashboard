#!/usr/bin/env python3
"""
Device-wide dashboard settings (selected index profiles and their options),
stored in the settings table of the database so that all screens and the
notifications use the same profiles.
"""

import copy
import threading
from typing import Dict

from pm_correction import DEFAULT_PM25_CORRECTION, PM25_CORRECTIONS


class DashboardSettings:
    # Recommended defaults (restored by restore_defaults()):
    # - US EPA AQI: the most widely used index, real-time NowCast method of AirNow,
    #   continuous scale with health messages for sensitive groups;
    # - EN 16798-1 CO2 categories: the European standard for the ventilation of
    #   occupied rooms (outdoor level 420 ppm);
    # - WHO indoor noise guidelines (living area);
    # - Thom discomfort index – Kyle (1994), a simple temperature/humidity
    #   index for thermal discomfort;
    # - PM2.5 humidity correction of Barkjohn et al. (2021).
    DEFAULTS = {
        "aqi_profile": "us_epa",
        # {profile id: {option id: value}}, e.g. {"raw_who": {"pollutant": "pm10"}}
        "aqi_profile_options": {},
        "co2_profile": "co2_en16798",
        "co2_profile_options": {},
        "noise_profile": "who_1999_indoor",
        "noise_profile_options": {},
        "comfort_profile": "thom_kyle",
        "comfort_profile_options": {},
        # humidity correction of the PM2.5 readings of the Plantower sensors
        "pm25_correction": DEFAULT_PM25_CORRECTION,
    }
    PROFILE_SETTINGS = {"aqi_profile": "aqi", "co2_profile": "co2", "noise_profile": "noise", "comfort_profile": "comfort"}
    OPTION_SETTINGS = {"aqi_profile_options": "aqi", "co2_profile_options": "co2",
                       "noise_profile_options": "noise", "comfort_profile_options": "comfort"}

    def __init__(self, storage, aqi_profiles: Dict, comfort_profiles: Dict, logger,
                 co2_profiles: Dict = None, noise_profiles: Dict = None):
        self._storage = storage
        self._profiles = {"aqi": aqi_profiles, "comfort": comfort_profiles,
                          "co2": co2_profiles or {}, "noise": noise_profiles or {}}
        self._aqi_profiles = aqi_profiles
        self._comfort_profiles = comfort_profiles
        self._logger = logger
        self._lock = threading.Lock()
        self._current = self._load()

    @property
    def current(self) -> Dict:
        # self._current is never modified in place, update() replaces it with a new dict:
        # reading it does not need the lock, so the web server is not blocked while
        # update() waits for the database
        return copy.deepcopy(self._current)

    def _load(self) -> Dict:
        stored = self._storage.read_settings()
        settings = copy.deepcopy(self.DEFAULTS)
        for key in settings:
            if key not in stored:
                continue
            try:
                self._validate(key, stored[key])
                settings[key] = stored[key]
            except ValueError as e:
                self._logger.warning(f"Ignoring stored setting {key}: {e}")
        # the default profiles may have been removed or be invalid
        for key, kind in self.PROFILE_SETTINGS.items():
            profiles = self._profiles[kind]
            if settings[key] not in profiles:
                settings[key] = next(iter(profiles), None)
        return settings

    def _validate(self, key: str, value):
        if key in self.PROFILE_SETTINGS:
            if value not in self._profiles[self.PROFILE_SETTINGS[key]]:
                raise ValueError(f"unknown {self.PROFILE_SETTINGS[key]} profile {value!r}")
        elif key == "pm25_correction":
            if value not in PM25_CORRECTIONS:
                raise ValueError(f"unknown PM2.5 correction {value!r} (known: {sorted(PM25_CORRECTIONS)})")
        elif key in self.OPTION_SETTINGS:
            profiles = self._profiles[self.OPTION_SETTINGS[key]]
            if not isinstance(value, dict):
                raise ValueError(f"{key} must be an object")
            for profile_id, options in value.items():
                profile = profiles.get(profile_id)
                if profile is None:
                    raise ValueError(f"unknown {self.OPTION_SETTINGS[key]} profile {profile_id!r}")
                declared = {o["id"]: o for o in profile.get("options", [])}
                if not isinstance(options, dict):
                    raise ValueError(f"options of {profile_id} must be an object")
                for option_id, option_value in options.items():
                    if option_id not in declared:
                        raise ValueError(f"profile {profile_id} has no option {option_id!r}")
                    if option_value not in declared[option_id]["values"]:
                        raise ValueError(f"invalid value {option_value!r} for option {option_id} of {profile_id}")
        else:
            raise ValueError(f"unknown setting {key!r}")

    def update(self, changes: Dict) -> Dict:
        """Validates and stores the given settings, raises ValueError if invalid."""
        for key, value in changes.items():
            self._validate(key, value)
        with self._lock:
            updated = copy.deepcopy(self._current)
            for key, value in changes.items():
                if key in self.OPTION_SETTINGS:
                    for profile_id, options in value.items():
                        updated[key].setdefault(profile_id, {}).update(options)
                else:
                    updated[key] = value
            self._storage.write_settings({key: updated[key] for key in changes})
            self._current = updated
            self._logger.info(f"Settings changed: {changes}")
            return copy.deepcopy(updated)

    def restore_defaults(self) -> Dict:
        """Restores the recommended profiles, options and PM2.5 correction."""
        with self._lock:
            defaults = copy.deepcopy(self.DEFAULTS)
            for key, kind in self.PROFILE_SETTINGS.items():
                if defaults[key] not in self._profiles[kind]:
                    defaults[key] = next(iter(self._profiles[kind]), None)
            self._storage.write_settings(defaults)
            self._current = defaults
            self._logger.info("Settings restored to the defaults")
            return copy.deepcopy(defaults)

    def options_of(self, kind: str, settings: Dict = None) -> Dict:
        """Options selected for the current profile of a kind ("aqi", "co2", "noise", "comfort")."""
        settings = settings or self.current
        return settings[f"{kind}_profile_options"].get(settings[f"{kind}_profile"], {})

    def aqi_options(self, settings: Dict = None) -> Dict:
        settings = settings or self.current
        return settings["aqi_profile_options"].get(settings["aqi_profile"], {})

    def comfort_options(self, settings: Dict = None) -> Dict:
        settings = settings or self.current
        return settings["comfort_profile_options"].get(settings["comfort_profile"], {})
