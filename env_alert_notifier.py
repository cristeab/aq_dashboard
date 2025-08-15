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
from constants import SLEEP_DURATION_SECONDS, normalize_and_format_time
from logger_configurator import LoggerConfigurator


MISSING_DATA_ALERT_INTERVAL_SEC = 10 * 60
# Configuration - update with your details
GMAIL_USER = os.getenv("GMAIL_USER")  # Gmail email address, set as env var
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")  # Gmail app password, set as env var

ALERT_STATE_FILE = "alert_state.json"

last_missing_data_alert = {}       # param: last alert timestamp

logger = LoggerConfigurator.configure_logger("EnvAlertNotifier")
# InfluxDB connection
storage = PersistentStorage()

# Define thresholds for parameters to monitor
THRESHOLDS = {
    "aqi": {
        "good": 50,
        "moderate": 100,
        "unhealthy_sensitive": 150,
        "unhealthy": 200,
        "very_unhealthy": 300,
        "hazardous": 500
    },
    "temperature": {
        "very_cold_celsius": 0.0,
        "cold_celsius": 10.0,
        "normal_celsius": 20.0,
        "hot_celsius": 30.0,
        "very_hot_celsius": 35.0
    },
    "relative_humidity": {
        "low": 30.0,
        "normal": 40.0,
        "high": 50.0
    },
    "noise": {
        "low_dB": 30.0,
        "normal_dB": 40.0,
        "high_dB": 50.0,
        "very_high_dB": 60.0
    },
    "gas": {
        "very_low_kohms": 50,
        "low_kohms": 100,
        "normal_kohms": 150,
        "high_kohms": 200
    },
    "visible_light": {
        "very_low_lux": 5,
        "low_lux": 50,
        "normal_lux": 100
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

def send_email_alert(parameter, value, threshold, timestamp):
    print(f"Sending alert for {parameter}: {value} crossed threshold {threshold} at {timestamp}")
    return  # Commented out to avoid sending emails during testing
    msg = EmailMessage()
    msg['From'] = GMAIL_USER
    msg['To'] = GMAIL_USER
    msg['Subject'] = f"Alert: {parameter} crossed threshold!"

    body = (f"Alert: {parameter} crossed the threshold!\n"
            f"Current value: {value}\n"
            f"Threshold: {threshold}\n"
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
    print(f"Sending missing data alert for {parameter}")
    return  # Commented out to avoid sending emails during testing
    msg = EmailMessage()
    msg['From'] = GMAIL_USER
    msg['To'] = GMAIL_USER
    msg['Subject'] = f"Alert: Missing data for {parameter}!"

    body = (f"Alert: No data received for parameter '{parameter}' in the last check.\n"
            f"Timestamp: {datetime.now()}\n")
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
    last = last_missing_data_alert.get("aqi", 0)
    if current_time - last > MISSING_DATA_ALERT_INTERVAL_SEC:
        send_missing_data_alert(parameter)
        last_missing_data_alert[parameter] = current_time

def query_latest_data():
    data = {}

    # Read AQI data
    aqi_data = storage.read_aqi()
    sendAlert = True
    if aqi_data is not None:
        try:
            data["aqi"] = {
                "timestamp": normalize_and_format_time(aqi_data["time"]),
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
                "timestamp": normalize_and_format_time(noise_level_db["time"]),
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
            ts = normalize_and_format_time(ambient_data["time"])
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
                "timestamp": normalize_and_format_time(light_data["time"]),
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
                continue  # Skip if no data
        except KeyError:
            continue

        param_thresholds = THRESHOLDS.get(param)
        if param_thresholds is None:
            continue

        # Ensure alert_state[param] is a dict
        if param not in alert_state:
            alert_state[param] = {}

        for threshold_name, threshold_value in param_thresholds.items():
            crossed = value > threshold_value
            previous_state = alert_state[param].get(threshold_name, False)
            # Send alert only if crossing from False to True
            if crossed and not previous_state:
                send_email_alert(f"{param}:{threshold_name}", value, threshold_value, timestamp)
                alert_state[param][threshold_name] = True
            # Reset alert state if value goes back below threshold
            elif not crossed and previous_state:
                alert_state[param][threshold_name] = False

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
