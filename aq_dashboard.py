#!/usr/bin/env python3

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import asyncio
from persistent_storage import PersistentStorage
from env_alert_notifier import EnvAlertNotifier
from fastapi.websockets import WebSocketDisconnect
from constants import SLEEP_DURATION_SECONDS, normalize_and_format_pandas_timestamp
from logger_configurator import LoggerConfigurator


app = FastAPI()

# Serve static files (HTML, JS, CSS)
app.mount("/static", StaticFiles(directory="static"), name="static")

# InfluxDB connection
storage = PersistentStorage()

# Alert notifier
notifier = EnvAlertNotifier()

# Logger
logger = LoggerConfigurator.configure_logger("AqDashboard")

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
            is_data_missing = True
            aqi_data = storage.read_aqi()
            if aqi_data is not None:
                try:
                    ts = normalize_and_format_pandas_timestamp(aqi_data["time"])
                    payload = {
                        "timestamp": ts,
                        "aqi": aqi_data["pm25_cf1_aqi"]
                    }
                    notifier.check_thresholds_and_alert("aqi", aqi_data["pm25_cf1_aqi"], ts, aqi_data["time"])
                    is_data_missing = False
                except Exception as e:
                    logger.error(f"Error processing AQI data: {e}")
            if is_data_missing:
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
                    except KeyError as e:
                        logger.error(f"KeyError processing PM{i} data: {e}")
            # Noise
            is_data_missing = True
            noise_level_db = storage.read_sound_pressure_level()
            if noise_level_db is not None:
                try:
                    ts = normalize_and_format_pandas_timestamp(noise_level_db["time"])
                    payload = payload | {
                        "noise": noise_level_db["sound_pressure_level"]
                    }
                    notifier.check_thresholds_and_alert("noise", noise_level_db["sound_pressure_level"], ts, noise_level_db["time"])
                    is_data_missing = False
                except Exception as e:
                    logger.error(f"Error processing noise data: {e}")
            if is_data_missing:
                notifier.send_missing_data_alert_if_due("noise")
            # Ambient
            is_data_missing = True
            ambient_data = storage.read_ambient_data()
            if ambient_data is not None:
                try:
                    ts = normalize_and_format_pandas_timestamp(ambient_data["time"])
                    payload = payload | {
                        "temperature": ambient_data["temperature"],
                        "relative_humidity": ambient_data["relative_humidity"],
                        "pressure": ambient_data["pressure"]
                    }
                    notifier.check_thresholds_and_alert("temperature", ambient_data["temperature"], ts, ambient_data["time"])
                    notifier.check_thresholds_and_alert("relative_humidity", ambient_data["relative_humidity"], ts, ambient_data["time"])
                    notifier.check_thresholds_and_alert("pressure", ambient_data["pressure"], ts, ambient_data["time"])
                    is_data_missing = False
                except Exception as e:
                    logger.error(f"Error processing ambient data: {e}")
            if is_data_missing:
                notifier.send_missing_data_alert_if_due("temperature, relative_humidity, gas, iaq_index")
            # Light
            is_data_missing = True
            light_data = storage.read_light_data()
            if light_data is not None:
                try:
                    ts = normalize_and_format_pandas_timestamp(light_data["time"])
                    payload = payload | {
                        "visible_light_lux": light_data["visible_light_lux"],
                        "uv_index": light_data["uv_index"]
                    }
                    notifier.check_thresholds_and_alert("visible_light", light_data["visible_light_lux"], ts, light_data["time"])
                    is_data_missing = False
                except Exception as e:
                    logger.error(f"Error processing light data: {e}")
            if is_data_missing:
                notifier.send_missing_data_alert_if_due("visible_light")
            # CO2
            is_data_missing = True
            co2_data = storage.read_co2_data()
            if co2_data is not None:
                try:
                    ts = normalize_and_format_pandas_timestamp(co2_data["time"])
                    payload = payload | {
                        "co2": co2_data["co2"]
                    }
                    notifier.check_thresholds_and_alert("co2", co2_data["co2"], ts, co2_data["time"])
                    is_data_missing = False
                except Exception as e:
                    logger.error(f"Error processing CO2 data: {e}")
            if is_data_missing:
                notifier.send_missing_data_alert_if_due("co2")
            # VOC and NOx
            is_data_missing = True
            sgp41_data = storage.read_sgp41_data()
            if sgp41_data is not None:
                try:
                    ts = normalize_and_format_pandas_timestamp(sgp41_data["time"])
                    payload = payload | {
                        "voc": sgp41_data["voc_index"],
                        "nox": sgp41_data["nox_index"]
                    }
                    notifier.check_thresholds_and_alert("voc_index", sgp41_data["voc_index"], ts, sgp41_data["time"])
                    notifier.check_thresholds_and_alert("nox_index", sgp41_data["nox_index"], ts, sgp41_data["time"])
                    is_data_missing = False
                except Exception as e:
                    logger.error(f"Error processing SGP41 data: {e}")
            if is_data_missing:
                notifier.send_missing_data_alert_if_due("voc_index, nox_index")
            # Radon
            is_data_missing = True
            radon_data = storage.read_radon_data()
            if radon_data is not None:
                try:
                    ts = normalize_and_format_pandas_timestamp(radon_data["time"])
                    payload = payload | {
                        "radon_1day_avg": radon_data["radon_1day_avg"],
                        "radon_week_avg": radon_data["radon_week_avg"],
                        "radon_year_avg": radon_data["radon_year_avg"]
                    }
                    notifier.check_thresholds_and_alert("radon_1day_avg", radon_data["radon_1day_avg"], ts, radon_data["time"])
                    notifier.check_thresholds_and_alert("radon_week_avg", radon_data["radon_week_avg"], ts, radon_data["time"])
                    notifier.check_thresholds_and_alert("radon_year_avg", radon_data["radon_year_avg"], ts, radon_data["time"])
                    is_data_missing = False
                except Exception as e:
                    logger.error(f"Error processing radon data: {e}")
            if is_data_missing:
                notifier.send_missing_data_alert_if_due("radon_data")
            # O3 and NO2
            is_data_missing = True
            zmod4510_data = storage.read_zmod4510_data()
            if zmod4510_data is not None:
                try:
                    ts = normalize_and_format_pandas_timestamp(zmod4510_data["time"])
                    payload = payload | {
                        "o3": zmod4510_data["o3_ppb"],
                        "no2": zmod4510_data["no2_ppb"]
                    }
                    notifier.check_thresholds_and_alert("o3", zmod4510_data["o3_ppb"], ts, zmod4510_data["time"])
                    notifier.check_thresholds_and_alert("no2", zmod4510_data["no2_ppb"], ts, zmod4510_data["time"])
                    is_data_missing = False
                except Exception as e:
                    logger.error(f"Error processing ZMOD4510 data: {e}")
            if is_data_missing:
                notifier.send_missing_data_alert_if_due("o3, no2")
            # CO
            is_data_missing = True
            co_data = storage.read_co_data()
            if co_data is not None:
                try:
                    ts = normalize_and_format_pandas_timestamp(co_data["time"])
                    payload = payload | {
                        "co": co_data["co_ppm"]
                    }
                    notifier.check_thresholds_and_alert("co", co_data["co_ppm"], ts, co_data["time"])
                    is_data_missing = False
                except Exception as e:
                    logger.error(f"Error processing CO data: {e}")
            if is_data_missing:
                notifier.send_missing_data_alert_if_due("co")
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
