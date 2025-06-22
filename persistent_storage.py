#!/usr/bin/env python3
#
# sudo systemctl status influxdb3-core
# journalctl -u influxdb3-core
# influxdb3 show databases
# curl "http://localhost:8181/health" --header "Authorization: Bearer $INFLUXDB3_ADMIN_TOKEN"

from influxdb_client_3 import InfluxDBClient3, WritePrecision, Point
from typing import Dict
from logger_configurator import LoggerConfigurator
from enum import Enum
import pandas
import os, sys


class PersistentStorage:
    auth_scheme = "Bearer"
    host = "http://localhost:8181"

    class Database(Enum):
        PM = "pm"
        AQI = "aqi"
        Noise = "noise"
        Temperature = "temperature"

    class Point(Enum):
        PM = "air_quality_data_"
        AQI = "air_quality_data"
        Noise = "noise_level"
        Temperature = "ambient_data"

    def __init__(self):
        self._logger = LoggerConfigurator.configure_logger(self.__class__.__name__)
        self._token = os.environ.get("INFLUXDB3_AUTH_TOKEN")
        if not self._token:
            print("Error: INFLUXDB3_AUTH_TOKEN environment variable is not set.")
            sys.exit(1)

        self._clients: Dict[str, InfluxDBClient3] = {}
        self._verify_token()

    def get_client(self, database: str) -> InfluxDBClient3:
        """Get or create a client for specific database"""
        if database not in self._clients:
            self._clients[database] = InfluxDBClient3(
                host=self.host,
                token=self._token,
                database=database,
                auth_scheme=self.auth_scheme
            )
        return self._clients[database]

    def _verify_token(self):
        try:
            client = self.get_client(self.Database.PM.value)
            client.query("SELECT 1")
            self._logger.info("Token verification successful.")
        except Exception as e:
            if "unauthorized" in str(e).lower() or "authentication" in str(e).lower():
                self._logger.error(f"Token verification failed: {e}")
            else:
                self._logger.error(f"An unexpected error occurred during token verification: {e}")
            sys.exit(1)

    def _write(self, db: Database, point: Point):
        client = self.get_client(db.value)
        # Supports writing Points, DataFrames, line protocol
        client.write(record=point, write_precision=WritePrecision.MS)

    def write_pm(self, i, sample):
        point = (
            Point(f"{self.Point.PM.value}{i}")
            .time(sample.timestamp)
            .field("pm10_cf1", sample.pm10_cf1)
            .field("pm25_cf1", sample.pm25_cf1)
            .field("pm100_cf1", sample.pm100_cf1)
            .field("pm10_std", sample.pm10_std)
            .field("pm25_std", sample.pm25_std)
            .field("pm100_std", sample.pm100_std)
            .field("gr03um", sample.gr03um)
            .field("gr05um", sample.gr05um)
            .field("gr10um", sample.gr10um)
            .field("gr25um", sample.gr25um)
            .field("gr50um", sample.gr50um)
            .field("gr100um", sample.gr100um)
        )
        self._write(self.Database.PM, point)

    def write_aqi(self, timestamp, pm25_cf1_aqi):
        point = (
            Point(self.Point.AQI.value)
            .time(timestamp)
            .field("pm25_cf1_aqi", pm25_cf1_aqi)
        )
        self._write(self.Database.AQI, point)

    def write_noise_level(self, timestamp, noise_level):
        point = (
            Point(self.Point.Noise.value)
            .time(timestamp)
            .field("noise_level", noise_level)
        )
        self._write(self.Database.Noise, point)

    def write_ambient_data(self, timestamp, temperature, gas, relative_humidity, pressure, iaq):
        point = (
            Point(self.Point.Temperature.value)
            .time(timestamp)
            .field("temperature", temperature)
            .field("gas", gas)
            .field("relative_humidity", relative_humidity)
            .field("pressure", pressure)
            .field("iaq", iaq)
        )
        self._write(self.Database.Temperature, point)

    def _read(self, db: Database, point_name):
        try:
            client = self.get_client(db.value)
            df = client.query(
                        query=f'SELECT * FROM "{point_name}" ORDER BY time DESC LIMIT 1',
                        language="sql",
                        mode="pandas"
                    )
            records = df.to_dict(orient="records")
            return records[-1] if records else None
        except Exception as e:
            pass
        return None

    def read_pm(self, i: int):
        return self._read(self.Database.PM, f'{self.Point.PM.value}{i}')

    def read_aqi(self):
        return self._read(self.Database.AQI, self.Point.AQI.value)

    def read_noise_level(self):
        return self._read(self.Database.Noise, self.Point.Noise.value)

    def read_ambient_data(self):
        return self._read(self.Database.Temperature, self.Point.Temperature.value)


if __name__ == "__main__":
    storage = PersistentStorage()
    for i in range(2):
        data = storage.read_pm(i)
        print(data)
    data = storage.read_aqi()
    print(data)
