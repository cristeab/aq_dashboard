#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import os
import sys
import json
import smtplib
import time
from email.message import EmailMessage
from datetime import datetime
from persistent_storage import PersistentStorage
from constants import SLEEP_DURATION_SECONDS, normalize_and_format_pandas_timestamp
from logger_configurator import LoggerConfigurator

MISSING_DATA_ALERT_INTERVAL_SEC = 10 * 60

# Configuration - update with your details
GMAIL_USER = os.getenv("GMAIL_USER") # Gmail email address, set as env var
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD") # Gmail app password, set as env var
ALERT_STATE_FILE = "alert_state.json"

last_missing_data_alert = {} # param: last alert timestamp

logger = LoggerConfigurator.configure_logger("EnvAlertNotifier")

# InfluxDB connection
storage = PersistentStorage()

# Define thresholds as intervals with descriptions
THRESHOLDS = {
    "aqi": {
        "intervals": [
            {"min": 0, "max": 50, "name": "good", "description": "Air quality is satisfactory"},
            {"min": 50, "max": 100, "name": "moderate", "description": "Air quality is acceptable for most people"},
            {"min": 100, "max": 150, "name": "unhealthy_sensitive", "description": "Members of sensitive groups may experience health effects"},
            {"min": 150, "max": 200, "name": "unhealthy", "description": "Everyone may begin to experience health effects"},
            {"min": 200, "max": 300, "name": "very_unhealthy", "description": "Health warnings of emergency conditions"},
            {"min": 300, "max": 500, "name": "hazardous", "description": "Health alert - everyone may experience serious health effects"}
        ]
    },
    "temperature": {
        "intervals": [
            {"min": -50, "max": 0, "name": "very_cold", "description": "Freezing conditions - potential health risk"},
            {"min": 0, "max": 10, "name": "cold", "description": "Cold conditions - additional heating recommended"},
            {"min": 10, "max": 16, "name": "cool", "description": "Cool conditions - below optimal comfort"},
            {"min": 16, "max": 18, "name": "normal", "description": "Acceptable temperature - WHO minimum standard"},
            {"min": 18, "max": 20, "name": "comfortable", "description": "Comfortable temperature - optimal lower range"},
            {"min": 20, "max": 24, "name": "warm", "description": "Warm conditions - upper comfort range"},
            {"min": 24, "max": 27, "name": "hot", "description": "Hot conditions - above optimal comfort"},
            {"min": 27, "max": 100, "name": "very_hot", "description": "Very hot conditions - potential health concern"}
        ]
    },
    "relative_humidity": {
        "intervals": [
            {"min": 0, "max": 20, "name": "very_low", "description": "Very low humidity - respiratory discomfort likely"},
            {"min": 20, "max": 30, "name": "low", "description": "Low humidity - may cause dry skin and respiratory irritation"},
            {"min": 30, "max": 40, "name": "normal", "description": "Acceptable humidity - WHO minimum comfort standard"},
            {"min": 40, "max": 50, "name": "comfortable", "description": "Comfortable humidity - optimal mid-range"},
            {"min": 50, "max": 60, "name": "high", "description": "High humidity - upper comfort limit"},
            {"min": 60, "max": 70, "name": "very_high", "description": "Very high humidity - dust mite risk"},
            {"min": 70, "max": 100, "name": "excessive", "description": "Excessive humidity - mold growth risk"}
        ]
    },
    "noise": {
        "intervals": [
            {"min": 0, "max": 25, "name": "very_quiet", "description": "Very quiet - ideal for sleep and concentration"},
            {"min": 25, "max": 30, "name": "quiet", "description": "Quiet - WHO bedroom nighttime standard"},
            {"min": 30, "max": 35, "name": "normal", "description": "Normal - WHO daytime living areas"},
            {"min": 35, "max": 45, "name": "moderate", "description": "Moderate - acceptable background noise"},
            {"min": 45, "max": 55, "name": "elevated", "description": "Elevated - WHO outdoor residential limit"},
            {"min": 55, "max": 65, "name": "high", "description": "High - may interfere with communication"},
            {"min": 65, "max": 75, "name": "very_high", "description": "Very high - potential sleep disruption"},
            {"min": 75, "max": 150, "name": "excessive", "description": "Excessive - hearing damage risk with prolonged exposure"}
        ]
    },
    "gas": {
        "intervals": [
            {"min": 200, "max": 1000, "name": "excellent", "description": "Excellent air quality - minimal VOCs detected"},
            {"min": 150, "max": 200, "name": "good", "description": "Good air quality - acceptable VOC levels"},
            {"min": 100, "max": 150, "name": "moderate", "description": "Moderate air quality - ventilation recommended"},
            {"min": 75, "max": 100, "name": "poor", "description": "Poor air quality - increase ventilation"},
            {"min": 50, "max": 75, "name": "very_poor", "description": "Very poor air quality - immediate action needed"},
            {"min": 0, "max": 50, "name": "hazardous", "description": "Hazardous air quality - source identification required"}
        ]
    },
    "visible_light": {
        "intervals": [
            {"min": 0, "max": 10, "name": "dark", "description": "Dark conditions - suitable for sleep"},
            {"min": 10, "max": 50, "name": "dim", "description": "Dim lighting - basic orientation possible"},
            {"min": 50, "max": 100, "name": "adequate", "description": "Adequate lighting - suitable for general activities"},
            {"min": 100, "max": 150, "name": "bright", "description": "Bright lighting - good for detailed tasks"},
            {"min": 150, "max": 1000, "name": "very_bright", "description": "Very bright - strong daylight exposure"}
        ]
    },
    "iaq_index": {
        "intervals": [
            {"min": 0, "max": 25, "name": "excellent", "description": "Excellent air quality - optimal conditions"},
            {"min": 25, "max": 50, "name": "good", "description": "Good air quality - healthy comfortable levels"},
            {"min": 50, "max": 75, "name": "moderate", "description": "Moderate air quality - ventilation advised"},
            {"min": 75, "max": 100, "name": "poor", "description": "Poor air quality - corrective action needed"},
            {"min": 100, "max": 500, "name": "very_poor", "description": "Very poor air quality - immediate mitigation required"}
        ]
    }
}

def load_alert_state():
    if os.path.exists(ALERT_STATE_FILE):
        with open(ALERT_STATE_FILE, "r") as f:
            return json.load(f)
    else:
        return {}

def save_alert_state(state):
    with open(ALERT_STATE_FILE, "w") as f:
        json.dump(state, f)

def get_interval_for_value(param, value):
    """Find which interval a value belongs to for a given parameter"""
    param_config = THRESHOLDS.get(param)
    if not param_config:
        return None
    
    for interval in param_config["intervals"]:
        if interval["min"] <= value < interval["max"]:
            return interval
    
    return None

def send_email_alert(parameter, value, interval, timestamp):
    logger.info(f"Sending alert for {parameter}: {value} entered '{interval['name']}' interval, '{interval['description']}', at {timestamp}")
    return # Commented out to avoid sending emails during testing

    msg = EmailMessage()
    msg['From'] = GMAIL_USER
    msg['To'] = GMAIL_USER
    msg['Subject'] = f"Alert: {parameter} - {interval['name'].title()} Level!"

    body = (f"Alert: {parameter} has entered the '{interval['name']}' interval!\n\n"
            f"Current value: {value}\n"
            f"Interval: {interval['name']} ({interval['min']} - {interval['max']})\n"
            f"Description: {interval['description']}\n"
            f"Timestamp: {timestamp}\n")

    msg.set_content(body)

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as smtp:
            smtp.starttls()
            smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            smtp.send_message(msg)
        logger.info(f"Alert email sent for {parameter}")
    except Exception as e:
        logger.error(f"Error sending email: {e}")

def send_missing_data_alert(parameter):
    localTime = normalize_and_format_pandas_timestamp()
    logger.info(f"Sending missing data alert for {parameter} at {localTime}")
    return # Commented out to avoid sending emails during testing

    msg = EmailMessage()
    msg['From'] = GMAIL_USER
    msg['To'] = GMAIL_USER
    msg['Subject'] = f"Alert: Missing data for {parameter}!"

    body = (f"Alert: No data received for parameter '{parameter}' in the last check.\n"
            f"Timestamp: {localTime}\n")

    msg.set_content(body)

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as smtp:
            smtp.starttls()
            smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            smtp.send_message(msg)
        logger.info(f"Missing data alert email sent for {parameter}")
    except Exception as e:
        logger.error(f"Error sending missing data email: {e}")

def send_missing_data_alert_if_due(parameter):
    global last_missing_data_alert
    current_time = time.time()
    last = last_missing_data_alert.get(parameter, 0)
    if current_time - last > MISSING_DATA_ALERT_INTERVAL_SEC:
        send_missing_data_alert(parameter)
        last_missing_data_alert[parameter] = current_time

def send_stt_alert(txt):
    localTime = normalize_and_format_pandas_timestamp()
    logger.info(f"STT '{txt}' at {localTime}")
    return # Commented out to avoid sending emails during testing

    msg = EmailMessage()
    msg['From'] = GMAIL_USER
    msg['To'] = GMAIL_USER
    msg['Subject'] = f"Alert: STT!"

    body = (f"Alert: STT '{txt}'.\n"
            f"Timestamp: {localTime}\n")

    msg.set_content(body)

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as smtp:
            smtp.starttls()
            smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            smtp.send_message(msg)
        logger.info(f"STT email sent")
    except Exception as e:
        logger.error(f"Error sending STT email: {e}")

def query_latest_data():
    data = {}
    
    # Read AQI data
    aqi_data = storage.read_aqi()
    sendAlert = True
    if aqi_data is not None:
        try:
            data["aqi"] = {
                "timestamp": normalize_and_format_pandas_timestamp(aqi_data["time"]),
                "value": aqi_data["pm25_cf1_aqi"]
            }
            sendAlert = False
        except KeyError:
            pass
    if sendAlert:
        send_missing_data_alert_if_due("aqi")

    # Read noise level
    noise_level_db = storage.read_noise_level()
    sendAlert = True
    if noise_level_db is not None:
        try:
            data["noise"] = {
                "timestamp": normalize_and_format_pandas_timestamp(noise_level_db["time"]),
                "value": noise_level_db["noise_level"]
            }
            sendAlert = False
        except KeyError:
            pass
    if sendAlert:
        send_missing_data_alert_if_due("noise")

    # Read ambient data
    ambient_data = storage.read_ambient_data()
    sendAlert = True
    if ambient_data is not None:
        try:
            ts = normalize_and_format_pandas_timestamp(ambient_data["time"])
            data["temperature"] = {
                "timestamp": ts,
                "value": ambient_data["temperature"]
            }
            data["relative_humidity"] = {
                "timestamp": ts,
                "value": ambient_data["relative_humidity"]
            }
            data["gas"] = {
                "timestamp": ts,
                "value": ambient_data["gas"]
            }
            # Add IAQ index if available
            if "iaq_index" in ambient_data:
                data["iaq_index"] = {
                    "timestamp": ts,
                    "value": ambient_data["iaq_index"]
                }
            sendAlert = False
        except KeyError:
            pass
    if sendAlert:
        send_missing_data_alert_if_due("ambient_data")

    # Read light data
    light_data = storage.read_light_data()
    sendAlert = True
    if light_data is not None:
        try:
            data["visible_light"] = {
                "timestamp": normalize_and_format_pandas_timestamp(light_data["time"]),
                "value": light_data["visible_light_lux"]
            }
            sendAlert = False
        except KeyError:
            pass
    if sendAlert:
        send_missing_data_alert_if_due("visible_light")

    return data

def check_thresholds_and_alert(data, alert_state):
    for param, info in data.items():
        try:
            value = info["value"]
            timestamp = info["timestamp"]
            if value is None:
                continue # Skip if no data
        except KeyError:
            continue

        # Get current interval for this value
        current_interval = get_interval_for_value(param, value)
        if current_interval is None:
            continue

        # Initialize alert state for this parameter if not exists
        if param not in alert_state:
            alert_state[param] = {"current_interval": None}

        # Get previous interval
        previous_interval = alert_state[param].get("current_interval")

        # Send alert if interval has changed
        if current_interval["name"] != previous_interval:
            send_email_alert(param, value, current_interval, timestamp)
            alert_state[param]["current_interval"] = current_interval["name"]

def main():
    # Check Gmail credentials environment variables
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print("Error: Please set GMAIL_USER and GMAIL_APP_PASSWORD environment variables.")
        return

    alert_state = load_alert_state()

    while True:
        try:
            data = query_latest_data()
            check_thresholds_and_alert(data, alert_state)
            save_alert_state(alert_state)
        except Exception as e:
            logger.error(f"Error during alert check: {e}")

        time.sleep(SLEEP_DURATION_SECONDS)

if __name__ == "__main__":
    main()