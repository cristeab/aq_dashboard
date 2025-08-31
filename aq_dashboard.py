#!/usr/bin/env python3

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import asyncio
from persistent_storage import PersistentStorage
from env_alert_notifier import EnvAlertNotifier
from fastapi.websockets import WebSocketDisconnect
from constants import SLEEP_DURATION_SECONDS, normalize_and_format_pandas_timestamp


app = FastAPI()

# Serve static files (HTML, JS, CSS)
app.mount("/static", StaticFiles(directory="static"), name="static")

# InfluxDB connection
storage = PersistentStorage()

# Alert notifier
notifier = EnvAlertNotifier()

@app.get("/", response_class=HTMLResponse)
async def root():
    with open("static/index.html", "r") as file:
        return file.read()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            # Query latest data from InfluxDB
            # AQI
            isDataMissing = True
            aqi_data = storage.read_aqi()
            if aqi_data is not None:
                try:
                    ts = normalize_and_format_pandas_timestamp(aqi_data["time"])
                    payload = {
                        "timestamp": ts,
                        "aqi": aqi_data["pm25_cf1_aqi"]
                    }
                    notifier.check_thresholds_and_alert("aqi", aqi_data["pm25_cf1_aqi"], ts, aqi_data["time"])
                    isDataMissing = False
                except KeyError:
                    pass
            if isDataMissing:
                payload = {}
                notifier.send_missing_data_alert_if_due("aqi")
            for i in range(2):
                pm_data = storage.read_pm(i)
                if pm_data is not None:
                    try:
                        payload = payload | {
                            "pm10_" + str(i): pm_data["pm10_cf1"],
                            "pm25_" + str(i): pm_data["pm25_cf1"],
                            "pm100_" + str(i): pm_data["pm100_cf1"],
                            "pm03plus_" + str(i): pm_data["gr03um"],
                            "pm05plus_" + str(i): pm_data["gr05um"],
                            "pm10plus_" + str(i): pm_data["gr10um"],
                            "pm25plus_" + str(i): pm_data["gr25um"],
                            "pm50plus_" + str(i): pm_data["gr50um"],
                            "pm100plus_" + str(i): pm_data["gr100um"]
                        }
                    except KeyError:
                        pass
            # Noise
            isDataMissing = True
            noise_level_db = storage.read_noise_level()
            if noise_level_db is not None:
                try:
                    ts = normalize_and_format_pandas_timestamp(noise_level_db["time"])
                    payload = payload | {
                        "noise": noise_level_db["noise_level"]
                    }
                    notifier.check_thresholds_and_alert("noise", noise_level_db["noise_level"], ts, noise_level_db["time"])
                    isDataMissing = False
                except KeyError:
                    pass
            if isDataMissing:
                notifier.send_missing_data_alert_if_due("noise")
            # Ambient
            isDataMissing = True
            ambient_data = storage.read_ambient_data()
            if ambient_data is not None:
                try:
                    ts = normalize_and_format_pandas_timestamp(ambient_data["time"])
                    payload = payload | {
                        "temperature": ambient_data["temperature"],
                        "relative_humidity": ambient_data["relative_humidity"],
                        "pressure": ambient_data["pressure"],
                        "gas": ambient_data["gas"],
                        "iaq": ambient_data["iaq"]
                    }
                    notifier.check_thresholds_and_alert("temperature", ambient_data["temperature"], ts, ambient_data["time"])
                    notifier.check_thresholds_and_alert("relative_humidity", ambient_data["relative_humidity"], ts, ambient_data["time"])
                    notifier.check_thresholds_and_alert("gas", ambient_data["gas"], ts, ambient_data["time"])
                    notifier.check_thresholds_and_alert("iaq_index", ambient_data["iaq"], ts, ambient_data["time"])
                    isDataMissing = False
                except KeyError:
                    pass
            if isDataMissing:
                notifier.send_missing_data_alert_if_due("temperature, relative_humidity, gas, iaq_index")
            # Light
            isDataMissing = True
            light_data = storage.read_light_data()
            if light_data is not None:
                try:
                    ts = normalize_and_format_pandas_timestamp(light_data["time"])
                    payload = payload | {
                        "visible_light_lux": light_data["visible_light_lux"],
                        "uv_index": light_data["uv_index"]
                    }
                    notifier.check_thresholds_and_alert("visible_light", light_data["visible_light_lux"], ts, light_data["time"])
                    isDataMissing = False
                except KeyError:
                    pass
            if isDataMissing:
                notifier.send_missing_data_alert_if_due("visible_light")
            # Send data to client
            data = {
                "type": "data",
                "payload": payload
            }
            await websocket.send_json(data)
            # Send notifications
            payload = notifier.get_notifications()
            if payload:
                data = {
                    "type": "notification",
                    "payload": payload
                }
                await websocket.send_json(data)
            # Wait before sending next update
            await asyncio.sleep(SLEEP_DURATION_SECONDS)
    except WebSocketDisconnect:
        print("Client disconnected")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8888, ssl_keyfile="key.pem", ssl_certfile="cert.pem")
