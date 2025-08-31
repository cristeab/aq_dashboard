#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import os
import sys
import json
import time
from datetime import datetime
from constants import normalize_and_format_pandas_timestamp
from logger_configurator import LoggerConfigurator


class EnvAlertNotifier:
    MISSING_DATA_ALERT_INTERVAL_SEC = 10 * 60
    ALERT_STATE_FILE = "alert_state.json"

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

    def __init__(self):
        self._last_missing_data_alert = {} # param: last alert timestamp
        self._logger = LoggerConfigurator.configure_logger("EnvAlertNotifier")
        # Load previous alert state
        self._alert_state = self.load_alert_state()
        # alerts dictionary
        self._alerts = {}

    def __del__(self):
        self.save_alert_state()

    def load_alert_state(self):
        if os.path.exists(self.ALERT_STATE_FILE):
            with open(self.ALERT_STATE_FILE, "r") as f:
                return json.load(f)
        else:
            return {}

    def save_alert_state(self):
        with open(self.ALERT_STATE_FILE, "w") as f:
            json.dump(self._alert_state, f)

    def _get_interval_for_value(self, param, value):
        param_config = self.THRESHOLDS.get(param)
        if not param_config:
            return None
        for interval in param_config["intervals"]:
            if interval["min"] <= value < interval["max"]:
                return interval
        return None

    def _send_data_alert(self, parameter, value, interval, timestamp):
        msg = f"{value} entered '{interval['name']}' interval, '{interval['description']}'"
        self._alerts[parameter] = {"message": msg, "timestamp": timestamp}
        self._logger.info(f"Sending alert for {parameter}: {msg}, at {timestamp}")

    def _send_missing_data_alert(self, parameter):
        timestamp = normalize_and_format_pandas_timestamp()
        msg = f"No data received for {parameter}"
        self._alerts[parameter] = {"message": msg, "timestamp": timestamp}
        self._logger.info(f"Sending missing data alert for {parameter} at {timestamp}")

    def send_missing_data_alert_if_due(self, parameter):
        current_time = time.time()
        last = self._last_missing_data_alert.get(parameter, 0)
        if current_time - last > self.MISSING_DATA_ALERT_INTERVAL_SEC:
            self._send_missing_data_alert(parameter)
            self._last_missing_data_alert[parameter] = current_time

    def check_thresholds_and_alert(self, param, value, timestamp):
        # Get current interval for this value
        current_interval = self._get_interval_for_value(param, value)
        if current_interval is None:
            return

        # Initialize alert state for this parameter if not exists
        if param not in self._alert_state:
            self._alert_state[param] = {"current_interval": None}

        # Get previous interval
        previous_interval = self._alert_state[param].get("current_interval")

        # Send alert if interval has changed
        if current_interval["name"] != previous_interval:
            self._send_data_alert(param, value, current_interval, timestamp)
            self._alert_state[param]["current_interval"] = current_interval["name"]
