#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import os
import sys
import json
import time
from datetime import datetime
from constants import normalize_and_format_pandas_timestamp
import pandas as pd
from logger_configurator import LoggerConfigurator
import subprocess


class EnvAlertNotifier:
    MISSING_DATA_ALERT_INTERVAL_SEC = 10 * 60

    # Define thresholds as intervals with descriptions
    THRESHOLDS = {
        "aqi": {
            "intervals": [
                {
                    "min": 0, "max": 50,
                    "name": "good",
                    "description": "Air quality is satisfactory"
                },
                {
                    "min": 50, "max": 100,
                    "name": "moderate",
                    "description": "Air quality is acceptable for most people"
                },
                {
                    "min": 100, "max": 150,
                    "name": "unhealthy_sensitive",
                    "description": "Members of sensitive groups may experience health effects"
                },
                {
                    "min": 150, "max": 200,
                    "name": "unhealthy",
                    "description": "Everyone may begin to experience health effects"
                },
                {
                    "min": 200, "max": 300,
                    "name": "very_unhealthy",
                    "description": "Health warnings of emergency conditions"
                },
                {
                    "min": 300, "max": 500,
                    "name": "hazardous",
                    "description": "Health alert - everyone may experience serious health effects"
                }
            ]
        },
        "temperature": {
            "intervals": [
                {
                    "min": -50, "max": 0,
                    "name": "very_cold",
                    "description": "Freezing conditions - potential health risk"
                },
                {
                    "min": 0, "max": 10,
                    "name": "cold",
                    "description": "Cold conditions - additional heating recommended"
                },
                {
                    "min": 10, "max": 16,
                    "name": "cool",
                    "description": "Cool conditions - below optimal comfort"
                },
                {
                    "min": 16, "max": 18,
                    "name": "normal",
                    "description": "Acceptable temperature - WHO minimum standard"
                },
                {
                    "min": 18, "max": 20,
                    "name": "comfortable",
                    "description": "Comfortable temperature - optimal lower range"
                },
                {
                    "min": 20, "max": 24,
                    "name": "warm",
                    "description": "Warm conditions - upper comfort range"
                },
                {
                    "min": 24, "max": 27,
                    "name": "hot",
                    "description": "Hot conditions - above optimal comfort"
                },
                {
                    "min": 27, "max": 100,
                    "name": "very_hot",
                    "description": "Very hot conditions - potential health concern"
                }
            ]
        },
        "relative_humidity": {
            "intervals": [
                {
                    "min": 0, "max": 20,
                    "name": "very_low",
                    "description": "Very low humidity - respiratory discomfort likely"
                },
                {
                    "min": 20, "max": 30,
                    "name": "low",
                    "description": "Low humidity - may cause dry skin and respiratory irritation"
                },
                {
                    "min": 30, "max": 40,
                    "name": "normal",
                    "description": "Acceptable humidity - WHO minimum comfort standard"
                },
                {
                    "min": 40, "max": 50,
                    "name": "comfortable",
                    "description": "Comfortable humidity - optimal mid-range"
                },
                {
                    "min": 50, "max": 60,
                    "name": "high",
                    "description": "High humidity - upper comfort limit"
                },
                {
                    "min": 60, "max": 70,
                    "name": "very_high",
                    "description": "Very high humidity - dust mite risk"
                },
                {
                    "min": 70, "max": 100,
                    "name": "excessive",
                    "description": "Excessive humidity - mold growth risk"
                }
            ]
        },
        "pressure": {
            "intervals": [
                {
                    "min": 300, "max": 980,
                    "name": "very_low",
                    "description": "Very low pressure - stormy weather likely"
                },
                {
                    "min": 980, "max": 1000,
                    "name": "low",
                    "description": "Low pressure - unsettled weather, possible rain"
                },
                {
                    "min": 1000, "max": 1023,
                    "name": "normal",
                    "description": "Normal pressure - stable weather conditions"
                },
                {
                    "min": 1023, "max": 1050,
                    "name": "high",
                    "description": "High pressure - fair weather"
                },
                {
                    "min": 1050, "max": 1100,
                    "name": "very_high",
                    "description": "Very high pressure - very dry conditions"
                }
            ]
        },
        "noise": {
            "intervals": [
                {
                    "min": 0, "max": 25,
                    "name": "very_quiet",
                    "description": "Very quiet - ideal for sleep and concentration"
                },
                {
                    "min": 25, "max": 30,
                    "name": "quiet",
                    "description": "Quiet - WHO bedroom nighttime standard"
                },
                {
                    "min": 30, "max": 35,
                    "name": "normal",
                    "description": "Normal - WHO daytime living areas"
                },
                {
                    "min": 35, "max": 45,
                    "name": "moderate",
                    "description": "Moderate - acceptable background noise"
                },
                {
                    "min": 45, "max": 55,
                    "name": "elevated",
                    "description": "Elevated - WHO outdoor residential limit"
                },
                {
                    "min": 55, "max": 65,
                    "name": "high",
                    "description": "High - may interfere with communication"
                },
                {
                    "min": 65, "max": 75,
                    "name": "very_high",
                    "description": "Very high - potential sleep disruption"
                },
                {
                    "min": 75, "max": 150,
                    "name": "excessive",
                    "description": "Excessive - hearing damage risk with prolonged exposure"
                }
            ]
        },
        "visible_light": {
            "intervals": [
                {
                    "min": 0, "max": 10,
                    "name": "dark",
                    "description": "Dark conditions - suitable for sleep"
                },
                {
                    "min": 10, "max": 50,
                    "name": "dim",
                    "description": "Dim lighting - basic orientation possible"
                },
                {
                    "min": 50, "max": 100,
                    "name": "adequate",
                    "description": "Adequate lighting - suitable for general activities"
                },
                {
                    "min": 100, "max": 150,
                    "name": "bright",
                    "description": "Bright lighting - good for detailed tasks"
                },
                {
                    "min": 150, "max": 1000,
                    "name": "very_bright",
                    "description": "Very bright - strong daylight exposure"
                }
            ]
        },
        "co2": {
            "intervals": [
                {
                    "min": 400, "max": 800,
                    "name": "good",
                    "description": "Typical outdoor fresh air levels - considered good/normal indoor air quality"
                },
                {
                    "min": 800, "max": 1000,
                    "name": "moderate",
                    "description": "Acceptable indoor air quality - may indicate moderate occupancy or ventilation"
                },
                {
                    "min": 1000, "max": 1500,
                    "name": "poor",
                    "description": "Poor indoor air quality - ventilation should be increased to avoid discomfort or health issues"
                },
                {
                    "min": 1500, "max": 2500,
                    "name": "very_poor",
                    "description": "High CO₂ concentration - can lead to drowsiness, decreased cognitive function, and discomfort"
                },
                {
                    "min": 2500, "max": 5000,
                    "name": "hazardous",
                    "description": "Very high concentration - potential health risk, immediate ventilation required"
                }
            ]
        },
        "voc_index": {
            "intervals": [
                {
                    "min": 0, "max": 200,
                    "name": "good",
                    "description": "The air is typical or better than usual for indoor environments, with minimal or no pollution events"
                },
                {
                    "min": 200, "max": 250,
                    "name": "moderate",
                    "description": "Minor pollution event detected; likely due to brief activities such as cooking, cleaning, or transient odors"
                },
                {
                    "min": 250, "max": 350,
                    "name": "poor",
                    "description": "Emissions from products, heavier cleaning, or increased occupancy"
                },
                {
                    "min": 350, "max": 400,
                    "name": "very_poor",
                    "description": "Persistent emissions or strong pollutant sources present"
                },
                {
                    "min": 400, "max": 500,
                    "name": "hazardous",
                    "description": "Prolonged exposure may cause discomfort or health effects"
                }
            ]
        },
        "nox_index": {
            "intervals": [
                {
                    "min": 0, "max": 50,
                    "name": "good",
                    "description": "Near background NOx levels, generally safe for indoor environments"
                },
                {
                    "min": 50, "max": 100,
                    "name": "moderate",
                    "description": "Slight increase, often related to brief combustion events (e.g., stove use, traffic infiltration)"
                },
                {
                    "min": 100, "max": 300,
                    "name": "poor",
                    "description": "Clear NOx event, likely from prolonged combustion (gas cooking, traffic, nearby industries)"
                },
                {
                    "min": 300, "max": 350,
                    "name": "very_poor",
                    "description": "High NOx; frequent and/or intense combustion sources nearby"
                },
                {
                    "min": 350, "max": 500,
                    "name": "hazardous",
                    "description": "Critically high NOx, levels associated with acute health risks for sensitive groups"
                }
            ]
        },
        "radon_1day_avg": {
            "intervals": [
                {
                    "min": 0, "max": 100,
                    "name": "good",
                    "description": "Radon levels are within safe limits."
                },
                {
                    "min": 100, "max": 150,
                    "name": "fair",
                    "description": "Elevated radon levels detected; consider mitigation."
                },
                {
                    "min": 150, "max": 1000,
                    "name": "poor",
                    "description": "Very high radon levels; immediate action required."
                }
            ]
        },
        "o3": {
            "intervals": [
                {
                    "min": 0, "max": 30,
                    "name": "good",
                    "description": "Clean air with minimal ozone; typical for well‑ventilated indoor spaces or low‑pollution outdoor conditions."
                },
                {
                    "min": 30, "max": 50,
                    "name": "moderate",
                    "description": "Acceptable air quality; sensitive individuals may begin to notice mild irritation during prolonged outdoor exposure."
                },
                {
                    "min": 50, "max": 70,
                    "name": "poor",
                    "description": "Above WHO guideline levels; may cause throat irritation, coughing, or reduced lung function during outdoor activity."
                },
                {
                    "min": 70, "max": 100,
                    "name": "very_poor",
                    "description": "Unhealthy for most people; prolonged exposure can aggravate respiratory conditions and reduce exercise capacity."
                },
                {
                    "min": 100, "max": 200,
                    "name": "hazardous",
                    "description": "High ozone concentration; can trigger asthma symptoms and significant respiratory stress—avoid outdoor exertion."
                }
            ]
        },
        "no2": {
            "intervals": [
                {
                    "min": 0, "max": 10,
                    "name": "good",
                    "description": "Very low NO₂ levels; typical of clean outdoor air or well‑ventilated indoor environments."
                },
                {
                    "min": 10, "max": 20,
                    "name": "moderate",
                    "description": "Acceptable air quality; may indicate nearby traffic or combustion sources but generally safe."
                },
                {
                    "min": 20, "max": 40,
                    "name": "poor",
                    "description": "Above WHO guideline levels; prolonged exposure may irritate airways, especially for sensitive individuals."
                },
                {
                    "min": 40, "max": 100,
                    "name": "very_poor",
                    "description": "Unhealthy concentration; can aggravate asthma and reduce lung function with repeated exposure."
                },
                {
                    "min": 100, "max": 200,
                    "name": "hazardous",
                    "description": "High NO₂ levels; associated with significant respiratory inflammation—avoid exposure and improve ventilation immediately."
                }
            ]
        },
        "co": {
            "intervals": [
                {
                    "min": 0,
                    "max": 10,
                    "name": "good",
                    "description": "Background CO typical of clean indoor or outdoor air; no expected health effects for the general population."
                },
                {
                    "min": 10,
                    "max": 30,
                    "name": "moderate",
                    "description": "Slightly elevated CO often from traffic, cooking, or heaters; generally safe for short exposure but should not be persistent."
                },
                {
                    "min": 30,
                    "max": 50,
                    "name": "unhealthy_sensitive",
                    "description": "Level where repeated or multi‑hour exposure may affect sensitive groups such as people with heart or respiratory conditions."
                },
                {
                    "min": 50,
                    "max": 100,
                    "name": "unhealthy",
                    "description": "Prolonged exposure can cause headache, fatigue, and reduced exercise tolerance; ventilation or source mitigation needed."
                },
                {
                    "min": 100,
                    "max": 200,
                    "name": "very_unhealthy",
                    "description": "Short‑term exposure may cause significant symptoms like dizziness and nausea; indicates a potentially dangerous situation."
                },
                {
                    "min": 200,
                    "max": 400,
                    "name": "hazardous",
                    "description": "High CO where exposure of tens of minutes can be life‑threatening; immediate evacuation and source shutdown required."
                },
                {
                    "min": 400,
                    "max": 500,
                    "name": "extreme_hazard",
                    "description": "Even short exposure can be rapidly fatal and demands urgent emergency response."
                }
            ]
        }
    }
    THRESHOLDS["radon_week_avg"] = THRESHOLDS["radon_1day_avg"]
    THRESHOLDS["radon_year_avg"] = THRESHOLDS["radon_1day_avg"]

    # define service restart mapping
    SERVICE_RESTARTS = {
        "aqi": "air_quality.service",
        "noise": "noise_sensor.service",
        "temperature, relative_humidity, gas, iaq_index": "ambient.service",
        "visible_light": "light_sensor.service",
        "co2": "carbon_dioxide_sensor.service",
        "voc_index, nox_index": "voc_nox_sensor.service",
        "radon_data": "radon_sensor.service",
        "o3, no2": "o3_no2_sensor.service",
        "co": "co_sensor.service"
    }

    def __init__(self):
        self._last_missing_data_alert = {} # param: last alert timestamp
        self._logger = LoggerConfigurator.configure_logger("EnvAlertNotifier")
        # Alerts state
        self._alert_state = {}
        # Alerts
        self._alerts = {}

    def __del__(self):
        self.save_alert_state()

    def _get_interval_for_value(self, param, value):
        param_config = self.THRESHOLDS.get(param)
        if not param_config:
            return None
        for interval in param_config["intervals"]:
            if interval["min"] <= value < interval["max"]:
                return interval
        return None

    @staticmethod
    def _get_measurement_unit(param):
        if param.startswith("radon"):
            return "Bq/m³"
        units = {
            "aqi": "",
            "temperature": "°C",
            "relative_humidity": "%",
            "pressure": "hPa",
            "noise": "dB",
            "visible_light": "lux",
            "co2": "ppm",
            "o3": "ppb",
            "no2": "ppb",
            "co": "ppm"
        }
        return units.get(param, "")

    def _send_data_alert(self, parameter, value, interval, formatted_timestamp, timestamp):
        msg = f"{value:.1f} {EnvAlertNotifier._get_measurement_unit(parameter)} entered '{interval['name']}' interval: {interval['description']}"
        self._alerts[parameter] = {
            "message": msg,
            "formatted_timestamp": formatted_timestamp,
            "timestamp": timestamp
            }
        self._logger.info(f"Sending alert for {parameter}: {msg}, at {formatted_timestamp}")

    def _send_missing_data_alert(self, parameter):
        timestamp = pd.Timestamp.now(tz='UTC')
        formatted_timestamp = normalize_and_format_pandas_timestamp(timestamp)
        msg = f"No data received for {parameter}"
        self._alerts[parameter] = {
            "message": msg,
            "formatted_timestamp": formatted_timestamp,
            "timestamp": timestamp
            }
        self._logger.info(f"Sending missing data alert for {parameter} at {formatted_timestamp}")

    def send_missing_data_alert_if_due(self, parameter):
        current_time = time.time()
        last = self._last_missing_data_alert.get(parameter, 0)
        if current_time - last > self.MISSING_DATA_ALERT_INTERVAL_SEC:
            self._send_missing_data_alert(parameter)
            self._last_missing_data_alert[parameter] = current_time
            service_name = self.SERVICE_RESTARTS.get(parameter)
            if service_name:
                self._restart_service(service_name)
            else:
                self._logger.warning(f"No service restart configured for parameter '{parameter}'")

    def check_thresholds_and_alert(self, param, value, formatted_timestamp, timestamp):
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
            self._send_data_alert(param, value, current_interval, formatted_timestamp, timestamp)
            self._alert_state[param]["current_interval"] = current_interval["name"]

    @staticmethod
    def _format_parameter(key):
        # Capitalize and replace underscores with spaces
        if "aqi" == key:
            return "AQI"
        elif "co2" == key:
            return "CO2"
        elif "voc_index" == key:
            return "TVOC Index"
        elif "nox_index" == key:
            return "NOx Index"
        elif "radon_1day_avg" == key:
            return "Radon 1-Day Avg"
        elif "radon_week_avg" == key:
            return "Radon Week Avg"
        elif "radon_year_avg" == key:
            return "Radon Year Avg"
        elif "o3" == key:
            return "O3"
        elif "no2" == key:
            return "NO2"
        elif "co" == key:
            return "CO"
        return key.replace('_', ' ').title()

    def get_notifications(self):
        if not self._alerts:
            return []
        notifications = [
            {
                "raw_timestamp": v["timestamp"],  # for sorting
                "timestamp": v["formatted_timestamp"],
                "parameter": EnvAlertNotifier._format_parameter(k),
                "message": v["message"]
            }
            for k, v in self._alerts.items()
        ]
        # Sort by timestamp descending
        try:
            notifications.sort(key=lambda x: x["raw_timestamp"], reverse=True)
        except Exception as e:
            self._logger.error(f"Error sorting {len(notifications)} notifications: {e}. Raw data: {[(n.get('parameter'), n.get('raw_timestamp')) for n in notifications]}")
        # Remove raw_timestamp field before returning
        return [
            {
                "timestamp": n["timestamp"],
                "parameter": n["parameter"],
                "message": n["message"]
            }
            for n in notifications
        ]

    def _restart_service(self, service_name):
        try:
            result = subprocess.run(
                ['sudo', 'systemctl', 'restart', service_name],
                check=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            self._logger.info(f"Service '{service_name}' restarted successfully.")
            if result.stdout:
                self._logger.debug(f"Output: {result.stdout}")
            if result.stderr:
                self._logger.error(f"Warning/Error Output: {result.stderr}")
        except subprocess.CalledProcessError as e:
            self._logger.error(f"Failed to restart service '{service_name}'.")
            self._logger.error(f"Return code: {e.returncode}")
            if e.stdout:
                self._logger.error(f"Output: {e.stdout}")
            if e.stderr:
                self._logger.error(f"Error output: {e.stderr}")
        except subprocess.TimeoutExpired:
            self._logger.error(f"Timeout expired while trying to restart service '{service_name}'.")
        except Exception as e:
            self._logger.error(f"Unexpected error: {e}")