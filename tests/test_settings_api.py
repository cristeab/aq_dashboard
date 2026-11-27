import importlib
import sys

import pytest

from dashboard_settings import DashboardSettings
from persistent_storage import PersistentStorage
from profile_loader import load_profiles

AQI, COMFORT = load_profiles("aqi"), load_profiles("comfort")
CO2, NOISE = load_profiles("co2"), load_profiles("noise")


def make_settings(storage, logger=None):
    return DashboardSettings(storage, AQI, COMFORT, logger or Logger(), co2_profiles=CO2, noise_profiles=NOISE)


class Logger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(message)

    warning = error = info


@pytest.fixture
def storage(tmp_path):
    s = PersistentStorage(str(tmp_path / "settings.db"))
    yield s
    s.close()


def test_defaults_and_persistence(storage):
    settings = make_settings(storage)
    assert settings.current == DashboardSettings.DEFAULTS
    assert settings.current["comfort_profile"] == "thom_kyle" and settings.current["co2_profile"] == "co2_en16798"
    settings.update({"aqi_profile": "raw_who", "aqi_profile_options": {"raw_who": {"pollutant": "no2"}}})
    settings.update({"comfort_profile": "humidex"})
    reloaded = make_settings(storage).current
    assert reloaded == {**DashboardSettings.DEFAULTS, "aqi_profile": "raw_who",
                        "aqi_profile_options": {"raw_who": {"pollutant": "no2"}}, "comfort_profile": "humidex"}
    assert make_settings(storage).aqi_options() == {"pollutant": "no2"}


@pytest.mark.parametrize("changes", [
    {"aqi_profile": "nope"}, {"comfort_profile": "us_epa"}, {"aqi_profile_options": {"raw_who": {"pollutant": "so2"}}},
    {"aqi_profile_options": {"us_epa": {"pollutant": "pm10"}}}, {"aqi_profile_options": []}, {"theme": "dark"},
])
def test_invalid_changes_are_rejected_and_not_stored(storage, changes):
    settings = make_settings(storage)
    with pytest.raises(ValueError):
        settings.update(changes)
    assert settings.current["aqi_profile"] == "us_epa" and storage.read_settings() == {}


def test_stored_settings_of_removed_profiles_fall_back(storage):
    storage.write_settings({"aqi_profile": "removed_profile", "comfort_profile": "thom_kyle"})
    logger = Logger()
    settings = make_settings(storage, logger)
    assert settings.current["aqi_profile"] == "us_epa" and settings.current["comfort_profile"] == "thom_kyle"
    # the CO2 profiles are no air quality index profiles any more
    storage.write_settings({"aqi_profile": "co2_uba"})
    assert make_settings(storage).current["aqi_profile"] == "us_epa"
    assert any("removed_profile" in m for m in logger.messages)


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("AQ_DB_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("AQ_AUTH", "on")
    sys.modules.pop("aq_dashboard", None)
    module = importlib.import_module("aq_dashboard")
    module.auth.create_user("admin", "correct horse")
    with TestClient(module.app) as test_client:
        test_client.module = module
        yield test_client
    module.storage.close()
    module.web_storage.close()
    sys.modules.pop("aq_dashboard", None)


def login(client, password="correct horse"):
    return client.post("/api/login", json={"username": "admin", "password": password})


def test_api_needs_a_login(client):
    assert client.get("/api/settings").status_code == 401
    assert client.get("/", follow_redirects=False).status_code == 303
    assert client.get("/login").status_code == 200 and client.get("/static/login.js").status_code == 200
    assert client.get("/api/auth/status").json() == {"enabled": True, "user": None, "setup_required": False,
                                                     "must_change_password": False}
    assert login(client, "wrong password").status_code == 401
    response = login(client)
    assert response.status_code == 200 and "httponly" in response.headers["set-cookie"].lower()
    assert "samesite=strict" in response.headers["set-cookie"].lower()
    assert client.get("/api/auth/status").json()["user"] == "admin"
    assert client.get("/", follow_redirects=False).status_code == 200
    client.post("/api/logout")
    assert client.get("/api/settings").status_code == 401


def test_cross_origin_requests_are_refused(client):
    login(client)
    response = client.put("/api/settings", json={"aqi_profile": "eea_eaqi"}, headers={"Origin": "http://evil.example"})
    assert response.status_code == 403
    assert client.put("/api/settings", json={"aqi_profile": "eea_eaqi"}, headers={"Origin": "http://testserver"}).status_code == 200


def test_api(client):
    login(client)
    profiles = client.get("/api/profiles").json()
    assert [p["id"] for p in profiles["aqi"]][:1] == ["us_epa"]
    assert {len(profiles[k]) for k in ("aqi", "co2", "noise", "comfort")} == {10, 2, 3, 6}
    assert not any(p["id"].startswith("co2") for p in profiles["aqi"])
    assert client.get("/api/settings").json()["aqi_profile"] == "us_epa"
    response = client.put("/api/settings", json={"aqi_profile": "china_mee", "noise_profile": "niosh_rel",
                                                  "co2_profile_options": {"co2_en16798": {"outdoor_co2": "450"}}})
    assert response.status_code == 200 and response.json()["aqi_profile"] == "china_mee"
    assert client.put("/api/settings", json={"co2_profile": "us_epa"}).status_code == 400
    response = client.put("/api/settings", json={"aqi_profile": "bogus"})
    assert response.status_code == 400 and "bogus" in response.json()["detail"]
    assert client.put("/api/settings", json={"unknown": 1}).status_code == 422
    restored = client.post("/api/settings/restore").json()
    assert restored == client.get("/api/settings/defaults").json() == client.get("/api/settings").json()
    assert client.get("/api/sensor-health").status_code == 200
    assert client.post("/api/sensor-health/reset").json() == {"ok": True}


def test_websocket_needs_a_login(client):
    from starlette.websockets import WebSocketDisconnect
    with client.websocket_connect("/ws") as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4401
    login(client)
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] in ("data", "notification")


def test_password_change_logs_out(client):
    login(client)
    session = client.cookies.get("aqd_session")
    change = {"current_password": "correct horse", "new_password": "battery staple"}
    assert client.post("/api/account/password", json={**change, "current_password": "wrong"}).status_code == 400
    assert client.post("/api/account/password", json={**change, "new_password": "password123"}).json()["detail"] == "password_too_weak"
    assert client.post("/api/account/password", json={**change, "new_password": "short"}).json()["detail"] == "password_too_short"
    assert client.post("/api/account/password", json={**change, "new_password": "correct horse"}).json()["detail"] == "password_unchanged"
    response = client.post("/api/account/password", json=change)
    assert response.status_code == 200 and response.json()["password_changed"]
    assert 'aqd_session=""' in response.headers["set-cookie"]                 # logged out
    assert client.module.auth.verify_token(session) is None                     # all the sessions end
    assert client.get("/api/settings").status_code == 401
    assert login(client, "correct horse").status_code == 401
    assert login(client, "battery staple").status_code == 200


def test_default_password_must_be_changed_after_the_first_login(client):
    from starlette.websockets import WebSocketDisconnect
    client.module.auth.create_user("demo", "aq-demo-2024", must_change=True, check_strength=False)
    response = client.post("/api/login", json={"username": "demo", "password": "aq-demo-2024"})
    assert response.status_code == 200 and response.json() == {"user": "demo", "must_change_password": True}
    assert client.get("/api/auth/status").json()["must_change_password"] is True
    # only the change of the password is allowed
    assert client.get("/api/settings").json()["detail"] == "password_change_required"
    assert client.get("/api/profiles").status_code == 403
    assert client.get("/", follow_redirects=False).status_code == 303
    with client.websocket_connect("/ws") as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4401
    change = {"current_password": "aq-demo-2024", "new_password": "aq-demo-2024"}
    assert client.post("/api/account/password", json=change).json()["detail"] == "password_unchanged"
    change["new_password"] = "demo-2025-aq"
    assert client.post("/api/account/password", json=change).json()["detail"] == "password_too_weak"
    change["new_password"] = "Velvet-Otter-93-Lamp"
    assert client.post("/api/account/password", json=change).status_code == 200
    response = client.post("/api/login", json={"username": "demo", "password": "Velvet-Otter-93-Lamp"})
    assert response.json() == {"user": "demo", "must_change_password": False}
    assert client.get("/api/settings").status_code == 200


def test_correction_and_profile_options(storage):
    settings = make_settings(storage)
    settings.update({"pm25_correction": "none", "comfort_profile": "iso7730_pmv",
                     "comfort_profile_options": {"iso7730_pmv": {"clo": "0.5", "met": "1.4"}},
                     "noise_profile_options": {"who_1999_indoor": {"room": "bedroom"}}})
    reloaded = make_settings(storage)
    assert reloaded.current["pm25_correction"] == "none"
    assert reloaded.options_of("comfort") == {"clo": "0.5", "met": "1.4"}
    assert reloaded.options_of("noise") == {"room": "bedroom"}
    for invalid in ({"pm25_correction": "magic"}, {"comfort_profile_options": {"iso7730_pmv": {"clo": "5"}}},
                    {"comfort_profile_options": {"thom_giles": {"clo": "0.5"}}}, {"noise_profile_options": {"who_1999_indoor": {"room": "kitchen"}}}):
        with pytest.raises(ValueError):
            settings.update(invalid)
    assert reloaded.restore_defaults() == DashboardSettings.DEFAULTS
    assert make_settings(storage).current == DashboardSettings.DEFAULTS


def test_dust_sensor_api(client):
    login(client)
    assert client.get("/api/dust-sensors").json()["state"] == "learning"
    assert len(client.post("/api/dust-sensors/reset").json()["baseline_start"]) == 10  # the next day, YYYY-MM-DD
    assert client.put("/api/settings", json={"pm25_correction": "epa_2022_extended"}).json()["pm25_correction"] == "epa_2022_extended"
    assert client.put("/api/settings", json={"pm25_correction": "bogus"}).status_code == 400
