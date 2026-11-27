import json
import os

import pytest

from profile_loader import PROFILES_DIR, ProfileError, load_profiles

LANGUAGES = {"en", "ro", "fr", "de"}


def all_texts(obj, path=""):
    """Yields (path, dict) for every localized text dict in a profile."""
    if isinstance(obj, dict):
        if "en" in obj and all(isinstance(v, str) for v in obj.values()):
            yield path, obj
            return
        for key, value in obj.items():
            yield from all_texts(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            yield from all_texts(value, f"{path}[{i}]")


@pytest.mark.parametrize("kind", ["aqi", "comfort"])
def test_all_shipped_profiles_are_valid(kind):
    profiles = load_profiles(kind)  # raises on the first invalid profile
    assert len(profiles) >= 4


@pytest.mark.parametrize("kind", ["aqi", "comfort"])
def test_all_texts_are_translated(kind):
    for profile_id, profile in load_profiles(kind).items():
        for path, texts in all_texts(profile):
            assert set(texts) == LANGUAGES, f"{kind}/{profile_id}{path}: {sorted(LANGUAGES - set(texts))} missing"


def write_profile(directory, profile):
    with open(os.path.join(directory, profile["id"] + ".json"), "w", encoding="utf-8") as f:
        json.dump(profile, f)


def broken(tmp_path, mutate):
    with open(os.path.join(PROFILES_DIR, "aqi", "us_epa.json"), encoding="utf-8") as f:
        profile = json.load(f)
    mutate(profile)
    write_profile(tmp_path, profile)
    return lambda: load_profiles("aqi", directory=str(tmp_path))


@pytest.mark.parametrize("mutate, message", [
    (lambda p: p["pollutants"]["pm25"][0]["breakpoints"].__setitem__(1, [5.0, 35.4, 51, 100]), "overlaps"),
    (lambda p: p["pollutants"]["pm25"][0].__setitem__("unit", "ppb"), "not valid for pm25"),
    (lambda p: p["categories"][0]["name"].pop("en"), "non-empty 'en'"),
    (lambda p: p["categories"][-1].__setitem__("to", 400), "scale maximum"),
    (lambda p: p["pollutants"]["o3"][0].__setitem__("averaging", {"type": "mean", "hours": 48}), "between 1 and 24"),
    (lambda p: p["pollutants"].__setitem__("voc", []), "unknown pollutant"),
    (lambda p: p["categories"][1].__setitem__("color", "yellow"), "#RRGGBB"),
])
def test_invalid_profiles_are_rejected(tmp_path, mutate, message):
    with pytest.raises(ProfileError, match=message):
        broken(tmp_path, mutate)()


def test_invalid_profiles_are_skipped_with_a_logger(tmp_path):
    class Logger:
        errors = []
        def error(self, message): self.errors.append(message)
    broken(tmp_path, lambda p: p["categories"][0].pop("color"))  # writes the invalid profile
    logger = Logger()
    assert load_profiles("aqi", directory=str(tmp_path), logger=logger) == {}
    assert "color" in logger.errors[0]


def test_circular_extends(tmp_path):
    write_profile(tmp_path, {"id": "a", "extends": "b"})
    write_profile(tmp_path, {"id": "b", "extends": "a"})
    with pytest.raises(ProfileError, match="circular"):
        load_profiles("aqi", directory=str(tmp_path))
