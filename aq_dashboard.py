#!/usr/bin/env python3
"""
Air quality dashboard web server.

A single background task reads the latest sensor data every few seconds,
computes the air quality, CO2, noise and thermal comfort indices with the
selected profiles, validates the sensors, checks the alert thresholds and
broadcasts the result to all connected (logged in) browsers over websockets.
The profiles, settings and sensor health are available through a small REST
API (/api/...). Optionally, the server advertises itself on the LAN (mDNS).
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Dict, List, Optional

from urllib.parse import urlparse

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, WebSocket
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.websockets import WebSocketDisconnect
from pydantic import BaseModel, ConfigDict

from aqi_engine import AqiEngine
from auth import AuthError, AuthManager
from comfort_engine import ComfortEngine
from constants import SLEEP_DURATION_SECONDS, format_local_timestamp
from dashboard_settings import DashboardSettings
from dust_sensor_monitor import DustSensorMonitor, alarm_message
from env_alert_notifier import EnvAlertNotifier
from logger_configurator import LoggerConfigurator
from noise_engine import NoiseEngine
from persistent_storage import PersistentStorage
from sensor_validation import SensorValidator, issue_message

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
CLIENT_SEND_TIMEOUT_SEC = 5

logger = LoggerConfigurator.configure_logger("AqDashboard")

# SQLite database connections: one for the update thread (long queries of the engines and
# of the sensor validation), one for the web requests, so that the requests never wait for them
storage = PersistentStorage()
web_storage = PersistentStorage()
# Index engines and their profiles; the CO2 and noise engines share the history of the AQI engine
aqi_engine = AqiEngine(storage, logger=logger)
co2_engine = AqiEngine(storage, logger=logger, kind="co2", history=aqi_engine.history)
noise_engine = NoiseEngine(aqi_engine.history, logger=logger)
comfort_engine = ComfortEngine(logger=logger)
if not all((aqi_engine.profiles, co2_engine.profiles, noise_engine.profiles, comfort_engine.profiles)):
    raise SystemExit("No valid air quality, CO2, noise or thermal comfort profile found in the profiles directory")
settings = DashboardSettings(web_storage, aqi_engine.profiles, comfort_engine.profiles, logger,
                             co2_profiles=co2_engine.profiles, noise_profiles=noise_engine.profiles)
# Health of the two dust sensors (drift, disagreement...), uses the history of the AQI engine
dust_monitor = DustSensorMonitor(storage, aqi_engine.history, logger)
# Validation of all the sensors with their historical data
validator = SensorValidator(storage, logger)
# User accounts and sessions
auth = AuthManager(web_storage, logger)
# Alert notifier
notifier = EnvAlertNotifier()


def _category(profile: Dict, category_id: str) -> Dict:
    return next(c for c in profile["categories"] if c["id"] == category_id)


def _issue_key(issue: Dict) -> str:
    """Unique key of a validation issue (several sensors may have the same issue)."""
    params = issue["params"]
    return ":".join(str(part) for part in (issue["code"], params.get("sensor_id", params.get("sensor")), params.get("quantity", "")))


def _read_sensors(payload: Dict, current_settings: Dict):
    """Adds the latest sensor values to the payload and checks the alert thresholds."""
    now = datetime.now(timezone.utc)
    now_formatted = format_local_timestamp(now)

    # Particulate matter (the header shows the time of the latest dust sample)
    latest_pm_time = None
    for i in range(2):
        pm_data = storage.read_pm(i)
        if pm_data is not None:
            latest_pm_time = max(latest_pm_time or pm_data["time"], pm_data["time"])
            payload.update({
                f"pm10_{i}": pm_data["pm10_cf1"],
                f"pm25_{i}": pm_data["pm25_cf1"],
                f"pm100_{i}": pm_data["pm100_cf1"],
                f"pm03plus_{i}": pm_data["gr03um"],
                f"pm05plus_{i}": pm_data["gr05um"],
                f"pm10plus_{i}": pm_data["gr10um"],
                f"pm25plus_{i}": pm_data["gr25um"],
                f"pm50plus_{i}": pm_data["gr50um"],
                f"pm100plus_{i}": pm_data["gr100um"],
            })
    if latest_pm_time is not None:
        payload["timestamp"] = format_local_timestamp(latest_pm_time)
        payload["time"] = latest_pm_time.isoformat()  # formatted by the browser in its language

    # Air quality index, computed with the selected profile
    aqi_profile = aqi_engine.profiles[current_settings["aqi_profile"]]
    air_index = None
    try:
        aqi_engine.refresh()
        air_index = aqi_engine.compute(aqi_profile["id"], settings.options_of("aqi", current_settings),
                                       current_settings["pm25_correction"])
    except Exception as e:
        logger.exception(f"Error computing the air quality index: {e}")
    # Dust sensor health: maintenance alarms (e.g. replace the sensors when they drift)
    try:
        dust_monitor.evaluate()
        notifier.set_maintenance_alerts("dust_sensors", dust_monitor.alarms,
                                        {a["code"]: alarm_message(a) for a in dust_monitor.alarms}, now_formatted, now)
    except Exception as e:
        logger.exception(f"Error checking the dust sensors: {e}")
    # Validation of all the sensors with their history (every few minutes)
    try:
        validator.evaluate(dust_alarms=dust_monitor.alarms)
        alarms = [dict(issue, key=_issue_key(issue)) for issue in validator.alarms]
        notifier.set_maintenance_alerts("sensors", alarms, {a["key"]: issue_message(a) for a in alarms}, now_formatted, now)
        payload["sensor_status"] = validator.status_by_sensor()
    except Exception as e:
        logger.exception(f"Error validating the sensors: {e}")
    if air_index is not None:
        payload["air_index"] = air_index
        notifier.check_category_and_alert("aqi", air_index["value"], air_index["display"], air_index.get("unit", ""),
                                          aqi_profile["id"], _category(aqi_profile, air_index["category"]),
                                          now_formatted, now)
    else:
        notifier.send_missing_data_alert_if_due("aqi")

    # Noise, and its equivalent level (LAeq) classified with the selected profile
    is_data_missing = True
    noise_level_db = storage.read_sound_pressure_level()
    if noise_level_db is not None:
        try:
            payload["noise"] = noise_level_db["sound_pressure_level"]
            noise_profile = noise_engine.profiles[current_settings["noise_profile"]]
            noise_index = noise_engine.compute(noise_profile["id"], settings.options_of("noise", current_settings))
            if noise_index is not None:
                payload["noise_index"] = noise_index
                notifier.check_category_and_alert("noise", noise_index["value"], noise_index["display"], noise_index["unit"],
                                                  noise_profile["id"], _category(noise_profile, noise_index["category"]),
                                                  now_formatted, now)
            is_data_missing = False
        except Exception as e:
            logger.exception(f"Error processing noise data: {e}")
    if is_data_missing:
        notifier.send_missing_data_alert_if_due("noise")

    # Ambient, and the thermal comfort index computed with the selected profile
    is_data_missing = True
    ambient_data = storage.read_ambient_data()
    if ambient_data is not None:
        try:
            ts = format_local_timestamp(ambient_data["time"])
            payload.update({
                "temperature": ambient_data["temperature"],
                "relative_humidity": ambient_data["relative_humidity"],
                "pressure": ambient_data["pressure"],
            })
            notifier.check_thresholds_and_alert("temperature", ambient_data["temperature"], ts, ambient_data["time"])
            notifier.check_thresholds_and_alert("relative_humidity", ambient_data["relative_humidity"], ts, ambient_data["time"])
            notifier.check_thresholds_and_alert("pressure", ambient_data["pressure"], ts, ambient_data["time"])
            comfort_profile = comfort_engine.profiles[current_settings["comfort_profile"]]
            comfort = comfort_engine.compute(comfort_profile["id"], ambient_data["temperature"],
                                             ambient_data["relative_humidity"], settings.options_of("comfort", current_settings))
            if comfort is not None:
                payload["comfort_index"] = comfort
                notifier.check_category_and_alert("comfort_index", comfort["value"], comfort["display"], comfort["unit"],
                                                  comfort_profile["id"], _category(comfort_profile, comfort["category"]),
                                                  ts, ambient_data["time"])
            is_data_missing = False
        except Exception as e:
            logger.error(f"Error processing ambient data: {e}")
    if is_data_missing:
        if notifier.send_missing_data_alert_if_due("temperature, relative_humidity, gas, iaq_index, thom_discomfort_index"):
            notifier.remove_data_alert("temperature")
            notifier.remove_data_alert("relative_humidity")
            notifier.remove_data_alert("pressure")
            notifier.remove_data_alert("comfort_index")
    else:
        notifier.remove_data_alert("temperature, relative_humidity, gas, iaq_index, thom_discomfort_index")

    # Light
    is_data_missing = True
    light_data = storage.read_light_data()
    if light_data is not None:
        try:
            ts = format_local_timestamp(light_data["time"])
            payload.update({
                "visible_light_lux": light_data["visible_light_lux"],
                "uv_index": light_data["uv_index"],
            })
            notifier.check_thresholds_and_alert("visible_light", light_data["visible_light_lux"], ts, light_data["time"])
            is_data_missing = False
        except Exception as e:
            logger.error(f"Error processing light data: {e}")
    if is_data_missing:
        notifier.send_missing_data_alert_if_due("visible_light")

    # CO2, and its (averaged) level classified with the selected indoor CO2 profile
    is_data_missing = True
    co2_data = storage.read_co2_data()
    if co2_data is not None:
        try:
            payload["co2"] = co2_data["co2"]
            co2_profile = co2_engine.profiles[current_settings["co2_profile"]]
            co2_index = co2_engine.compute(co2_profile["id"], settings.options_of("co2", current_settings))
            if co2_index is not None:
                payload["co2_index"] = co2_index
                notifier.check_category_and_alert("co2", co2_index["value"], co2_index["display"], co2_index["unit"],
                                                  co2_profile["id"], _category(co2_profile, co2_index["category"]),
                                                  now_formatted, now)
            is_data_missing = False
        except Exception as e:
            logger.exception(f"Error processing CO2 data: {e}")
    if is_data_missing:
        notifier.send_missing_data_alert_if_due("co2")

    # VOC and NOx
    is_data_missing = True
    sgp41_data = storage.read_sgp41_data()
    if sgp41_data is not None:
        try:
            ts = format_local_timestamp(sgp41_data["time"])
            payload.update({"voc": sgp41_data["voc_index"], "nox": sgp41_data["nox_index"]})
            notifier.check_thresholds_and_alert("voc_index", sgp41_data["voc_index"], ts, sgp41_data["time"])
            notifier.check_thresholds_and_alert("nox_index", sgp41_data["nox_index"], ts, sgp41_data["time"])
            is_data_missing = False
        except Exception as e:
            logger.error(f"Error processing SGP41 data: {e}")
    if is_data_missing:
        if notifier.send_missing_data_alert_if_due("voc_index, nox_index"):
            notifier.remove_data_alert("voc_index")
            notifier.remove_data_alert("nox_index")
    else:
        notifier.remove_data_alert("voc_index, nox_index")

    # Radon
    is_data_missing = True
    radon_data = storage.read_radon_data()
    if radon_data is not None:
        try:
            ts = format_local_timestamp(radon_data["time"])
            payload.update({
                "radon_1day_avg": radon_data["radon_1day_avg"],
                "radon_week_avg": radon_data["radon_week_avg"],
                "radon_year_avg": radon_data["radon_year_avg"],
            })
            notifier.check_thresholds_and_alert("radon_1day_avg", radon_data["radon_1day_avg"], ts, radon_data["time"])
            notifier.check_thresholds_and_alert("radon_week_avg", radon_data["radon_week_avg"], ts, radon_data["time"])
            notifier.check_thresholds_and_alert("radon_year_avg", radon_data["radon_year_avg"], ts, radon_data["time"])
            is_data_missing = False
        except Exception as e:
            logger.error(f"Error processing radon data: {e}")
    if is_data_missing:
        if notifier.send_missing_data_alert_if_due("radon_data"):
            notifier.remove_data_alert("radon_1day_avg")
            notifier.remove_data_alert("radon_week_avg")
            notifier.remove_data_alert("radon_year_avg")
    else:
        notifier.remove_data_alert("radon_data")

    # O3 and NO2
    is_data_missing = True
    zmod4510_data = storage.read_zmod4510_data()
    if zmod4510_data is not None:
        try:
            ts = format_local_timestamp(zmod4510_data["time"])
            payload.update({"o3": zmod4510_data["o3_ppb"], "no2": zmod4510_data["no2_ppb"]})
            notifier.check_thresholds_and_alert("o3", zmod4510_data["o3_ppb"], ts, zmod4510_data["time"])
            notifier.check_thresholds_and_alert("no2", zmod4510_data["no2_ppb"], ts, zmod4510_data["time"])
            is_data_missing = False
        except Exception as e:
            logger.error(f"Error processing ZMOD4510 data: {e}")
    if is_data_missing:
        if notifier.send_missing_data_alert_if_due("o3, no2"):
            notifier.remove_data_alert("o3")
            notifier.remove_data_alert("no2")
    else:
        notifier.remove_data_alert("o3, no2")

    # CO
    is_data_missing = True
    co_data = storage.read_co_data()
    if co_data is not None:
        try:
            ts = format_local_timestamp(co_data["time"])
            payload["co"] = co_data["co_ppm"]
            notifier.check_thresholds_and_alert("co", co_data["co_ppm"], ts, co_data["time"])
            is_data_missing = False
        except Exception as e:
            logger.error(f"Error processing CO data: {e}")
    if is_data_missing:
        notifier.send_missing_data_alert_if_due("co")


def collect_messages() -> List[Dict]:
    """Builds the websocket messages of one update cycle (runs in a worker thread)."""
    current_settings = settings.current
    payload = {}
    _read_sensors(payload, current_settings)
    messages = [{"type": "data", "payload": payload}]
    notifications = notifier.get_notifications()
    if notifications:
        messages.append({"type": "notification", "payload": notifications})
    return messages


class Broadcaster:
    """Produces the dashboard updates once and sends them to every connected client."""

    def __init__(self):
        self.clients = set()
        self.last_messages: List[Dict] = []
        self._wakeup: Optional[asyncio.Event] = None

    def request_update(self):
        """Triggers an immediate update (e.g. after a settings change)."""
        if self._wakeup is not None:
            self._wakeup.set()

    async def run(self):
        self._wakeup = asyncio.Event()
        while True:
            self._wakeup.clear()
            try:
                messages = await asyncio.to_thread(collect_messages)
            except Exception as e:
                logger.exception(f"Error collecting the dashboard data: {e}")
                messages = []
            if messages:
                self.last_messages = messages
                await self._broadcast(messages)
            try:
                await asyncio.wait_for(self._wakeup.wait(), SLEEP_DURATION_SECONDS)
            except asyncio.TimeoutError:
                pass

    async def _send(self, websocket: WebSocket, messages: List[Dict]):
        try:
            for message in messages:
                await asyncio.wait_for(websocket.send_json(message), CLIENT_SEND_TIMEOUT_SEC)
        except Exception:
            # disconnected or too slow: the websocket handler cleans up
            self.clients.discard(websocket)

    async def _broadcast(self, messages: List[Dict]):
        await asyncio.gather(*(self._send(ws, messages) for ws in list(self.clients)))


broadcaster = Broadcaster()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(broadcaster.run())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(lifespan=lifespan)

# Serve static files (HTML, JS, CSS, translations): public, the login page needs them
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


# ---------------------------------------------------------------- authentication

def _client(request) -> str:
    """Client address; behind the local Nginx reverse proxy, the one it forwards."""
    host = request.client.host if request.client else "unknown"
    if host in ("127.0.0.1", "::1") and request.headers.get("x-real-ip"):
        return request.headers["x-real-ip"]
    return host


def _is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


def session_user(request: Request) -> str:
    """User of a valid session, even if the password must still be changed."""
    if not auth.enabled:
        return "anonymous"
    session = auth.verify_session(request.cookies.get(auth.COOKIE))
    if session is None:
        raise HTTPException(status_code=401, detail="not_authenticated")
    request.state.must_change_password = session["must_change_password"]
    return session["user"]


def current_user(request: Request) -> str:
    """User of a valid session with a password that does not need to be changed."""
    user = session_user(request)
    if getattr(request.state, "must_change_password", False):
        raise HTTPException(status_code=403, detail="password_change_required")
    return user


def same_origin(request: Request):
    """Protection against cross-site requests for the requests that change something
    (in addition to the SameSite=Strict session cookie)."""
    origin = request.headers.get("origin")
    if origin:
        expected = request.headers.get("x-forwarded-host") or request.headers.get("host")
        if urlparse(origin).netloc != expected:
            raise HTTPException(status_code=403, detail="cross_origin_request")


def _set_session(response: Response, request: Request, username: str, remember: bool):
    response.set_cookie(auth.COOKIE, auth.make_token(username, remember),
                        max_age=auth.REMEMBER_SECONDS if remember else None, path="/",
                        httponly=True, samesite="strict", secure=_is_https(request))


class Credentials(BaseModel):
    username: str
    password: str
    remember: bool = False


class Setup(BaseModel):
    setup_code: str
    username: str
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


@app.get("/")
async def root(request: Request):
    if auth.enabled:
        session = await asyncio.to_thread(auth.verify_session, request.cookies.get(auth.COOKIE))
        if session is None or session["must_change_password"]:
            # relative: works behind the /aqd/ prefix; the login page asks for the new password
            return RedirectResponse("login", status_code=303)
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/login")
async def login_page():
    return FileResponse(os.path.join(STATIC_DIR, "login.html"))


@app.get("/api/auth/status")
async def auth_status(request: Request):
    if not auth.enabled:
        return {"enabled": False, "user": "anonymous", "setup_required": False, "must_change_password": False}
    session = await asyncio.to_thread(auth.verify_session, request.cookies.get(auth.COOKIE))
    return {"enabled": True, "user": session["user"] if session else None,
            "setup_required": not await asyncio.to_thread(auth.has_users),
            "must_change_password": bool(session and session["must_change_password"])}


@app.post("/api/login", dependencies=[Depends(same_origin)])
async def login(credentials: Credentials, request: Request, response: Response):
    try:
        user = await asyncio.to_thread(auth.login, credentials.username, credentials.password, _client(request))
    except AuthError as e:
        status = 429 if str(e).startswith("locked") else 401
        raise HTTPException(status_code=status, detail=str(e))
    _set_session(response, request, user, credentials.remember)
    # a default or temporary password: the login page asks for a new one before the dashboard
    return {"user": user, "must_change_password": await asyncio.to_thread(auth.must_change_password, user)}


@app.post("/api/setup", dependencies=[Depends(same_origin)])
async def setup(data: Setup, request: Request, response: Response):
    """First-run creation of the administrator account (needs the setup code of the log)."""
    try:
        await asyncio.to_thread(auth.setup, data.setup_code, data.username, data.password)
    except AuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _set_session(response, request, data.username, False)
    return {"user": data.username}


@app.post("/api/logout", dependencies=[Depends(same_origin)])
async def logout(response: Response):
    response.delete_cookie(auth.COOKIE, path="/")
    return {"user": None}


@app.post("/api/account/password", dependencies=[Depends(same_origin)])
async def change_password(change: PasswordChange, request: Request, response: Response,
                          user: str = Depends(session_user)):
    """Change of the password by the logged in user (also when it must be changed after the
    first login). The session ends: the user logs in again with the new password."""
    if not auth.enabled:
        raise HTTPException(status_code=400, detail="auth_disabled")
    try:
        await asyncio.to_thread(auth.change_password, user, change.current_password, change.new_password,
                                _client(request))
    except AuthError as e:
        status = 429 if str(e).startswith("locked") else 400
        raise HTTPException(status_code=status, detail=str(e))
    response.delete_cookie(auth.COOKIE, path="/")
    return {"user": None, "password_changed": True}


# ---------------------------------------------------------------- API (logged in users)

api = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


# the profiles are loaded once at startup: serialize them once instead of on every request
# (encoding the large nested structure took 0.1-0.2 s of the event loop on each page load)
_PROFILES_JSON = json.dumps(
    {"aqi": list(aqi_engine.profiles.values()), "co2": list(co2_engine.profiles.values()),
     "noise": list(noise_engine.profiles.values()), "comfort": list(comfort_engine.profiles.values())},
    ensure_ascii=False, separators=(",", ":")).encode()


@api.get("/profiles")
async def get_profiles():
    """All available profiles with their categories, texts and breakpoints."""
    return Response(_PROFILES_JSON, media_type="application/json")


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    aqi_profile: Optional[str] = None
    aqi_profile_options: Optional[Dict[str, Dict[str, str]]] = None
    co2_profile: Optional[str] = None
    co2_profile_options: Optional[Dict[str, Dict[str, str]]] = None
    noise_profile: Optional[str] = None
    noise_profile_options: Optional[Dict[str, Dict[str, str]]] = None
    comfort_profile: Optional[str] = None
    comfort_profile_options: Optional[Dict[str, Dict[str, str]]] = None
    pm25_correction: Optional[str] = None


@api.get("/settings")
async def get_settings():
    return settings.current


@api.put("/settings", dependencies=[Depends(same_origin)])
async def put_settings(update: SettingsUpdate):
    changes = update.model_dump(exclude_none=True)
    try:
        current = await asyncio.to_thread(settings.update, changes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    broadcaster.request_update()
    return current


@api.get("/settings/defaults")
async def get_default_settings():
    return DashboardSettings.DEFAULTS


@api.post("/settings/restore", dependencies=[Depends(same_origin)])
async def restore_default_settings():
    """Restores the recommended profiles, options and PM2.5 correction."""
    current = await asyncio.to_thread(settings.restore_defaults)
    broadcaster.request_update()
    return current


@api.get("/dust-sensors")
async def get_dust_sensors():
    """Health status of the two dust sensors (baseline, drift, alarms)."""
    return dust_monitor.status


@api.post("/dust-sensors/reset", dependencies=[Depends(same_origin)])
async def reset_dust_sensors():
    """After replacing the dust sensors: start a new baseline for the drift detection."""
    await asyncio.to_thread(dust_monitor.reset_baseline)
    broadcaster.request_update()
    return {"baseline_start": dust_monitor.baseline_start()}


@api.get("/sensor-health")
async def get_sensor_health():
    """Validation report of all the sensors."""
    return validator.report


@api.post("/sensor-health/reset", dependencies=[Depends(same_origin)])
async def reset_sensor_health():
    """After replacing or recalibrating a sensor: new baseline for the drift checks."""
    await asyncio.to_thread(validator.reset_baseline)
    broadcaster.request_update()
    return {"ok": True}


app.include_router(api)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    if auth.enabled:
        session = await asyncio.to_thread(auth.verify_session, websocket.cookies.get(auth.COOKIE))
        if session is None or session["must_change_password"]:
            await websocket.close(code=4401)  # the page goes to the login page
            return
    try:
        # show the latest data right away instead of waiting for the next update
        for message in broadcaster.last_messages:
            await websocket.send_json(message)
        broadcaster.clients.add(websocket)
        while True:
            # the clients do not send anything, this only detects the disconnection
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("Client disconnected")
    finally:
        broadcaster.clients.discard(websocket)


if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Air quality dashboard web server")
    parser.add_argument("--host", default="127.0.0.1", help="interface to listen on (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8888, help="port to listen on (default: 8888)")
    parser.add_argument("--advertise", action="store_true",
                        help="advertise the server on the LAN with mDNS (not needed when Avahi does it, see INSTALL.md)")
    args = parser.parse_args()

    if not os.path.isfile(os.path.join(STATIC_DIR, "styles.css")):
        logger.warning("static/styles.css is missing, the page will be unstyled. "
                       "Build it with: npx sass --no-source-map static/styles.scss static/styles.css")
        print("Warning: static/styles.css is missing, build it with: "
              "npx sass --no-source-map static/styles.scss static/styles.css")

    advertiser = None
    if args.advertise:
        try:
            from lan_discovery import Advertiser
            advertiser = Advertiser(port=args.port, path="/", logger=logger,
                                    addresses=None if args.host in ("0.0.0.0", "") else [args.host])
            advertiser.start()
        except Exception as e:  # e.g. zeroconf not installed
            logger.error(f"Cannot advertise the server on the LAN: {e}")
            print(f"Cannot advertise the server on the LAN: {e}")

    # The sans-I/O websockets implementation avoids the deprecated legacy websockets API
    config = uvicorn.Config(app, host=args.host, port=args.port, ws="websockets-sansio")
    # Load (import the protocol implementations) before the event loop starts
    # instead of blocking it during the startup
    config.load()
    try:
        uvicorn.Server(config).run()
    finally:
        if advertiser is not None:
            advertiser.stop()
