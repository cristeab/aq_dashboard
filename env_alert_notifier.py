#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import smtplib
from email.message import EmailMessage
from datetime import datetime
from persistent_storage import PersistentStorage
from constants import SLEEP_DURATION_SECONDS, normalize_and_format_time
import time


# Configuration - update with your details
GMAIL_USER = os.getenv("GMAIL_USER")  # Gmail email address, set as env var
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")  # Gmail app password, set as env var

ALERT_STATE_FILE = "alert_state.json"

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
        "low_lux": 50,
        "normal_lux": 150
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
        print(f"Alert email sent for {parameter}")
    except Exception as e:
        print(f"Error sending email: {e}")

def query_latest_data():
    data = {}

    # Read AQI data
    aqi_data = storage.read_aqi_data()
    if aqi_data is not None:
        try:
            data["aqi"] = {
                "timestamp": normalize_and_format_time(aqi_data["time"]),
                "value": aqi_data["pm25_cf1_aqi"]
            }
        except KeyError:
            pass

    # Read noise level
    noise_level_db = storage.read_noise_level()
    if noise_level_db is not None:
        try:
            data["noise"] = {
                "timestamp": normalize_and_format_time(noise_level_db["time"]),
                "value": noise_level_db["noise_level"]
            }
        except KeyError:
            pass

    # Read ambient data
    ambient_data = storage.read_ambient_data()
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
        except KeyError:
            pass

    # Read light data
    light_data = storage.read_light_data()
    if light_data is not None:
        try:
            data["visible_light"] = {
                "timestamp": normalize_and_format_time(light_data["time"]),
                "value": light_data["visible_light_lux"]
            }
        except KeyError:
            pass

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
        print("Please set GMAIL_USER and GMAIL_APP_PASSWORD environment variables.")
        return

    alert_state = load_alert_state()

    while True:
        try:
            data = query_latest_data()
            check_thresholds_and_alert(data, alert_state)
            save_alert_state(alert_state)
        except Exception as e:
            print(f"Error during alert check: {e}")
        time.sleep(SLEEP_DURATION_SECONDS)

if __name__ == "__main__":
    main()
