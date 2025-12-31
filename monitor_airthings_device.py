#!/usr/bin/env python3
"""
Periodically read an Airthings device by Bluetooth address and save sensor data into db.
"""
from __future__ import annotations
import os
import asyncio
import sys
from datetime import datetime, timezone
from bleak import BleakScanner
from airthings_ble import AirthingsBluetoothDeviceData, UnsupportedDeviceError
from constants import AIRTHINGS_SLEEP_DURATION_SECONDS, AIRTHINGS_SCAN_TIMEOUT_SECONDS
from persistent_storage import PersistentStorage
from logger_configurator import LoggerConfigurator
# Try to import DisconnectedError for finer-grained handling; fall back to None
try:
    from airthings_ble.parser import DisconnectedError  # type: ignore
except Exception:
    DisconnectedError = None


logger = LoggerConfigurator.configure_logger("AirthingsMonitor")
persistent_storage = PersistentStorage()
device_mac = os.environ.get("AIRTHINGS_DEVICE_MAC")
if not device_mac:
    print("Error: AIRTHINGS_DEVICE_MAC environment variable is not set.")
    sys.exit(1)


async def find_device_by_address(address: str, timeout: float):
    devices = await BleakScanner.discover(timeout=timeout)
    for d in devices:
        if d.address.lower() == address.lower():
            return d
    return None


async def read_device_once(address: str, timeout: float, is_metric: bool, logger: logging.Logger):
    target = await find_device_by_address(address, timeout)
    if target is None:
        logger.error(f"Device with address {address} not found during scan")
        return None

    client = AirthingsBluetoothDeviceData(logger=logger, is_metric=is_metric)
    device = await client.update_device(target)
    return device


def save_radon_data(device) -> None:
    timestamp = datetime.now(timezone.utc)
    sensors = device.sensors
    
    if "radon_1day_avg" in sensors:
        radon_1day = sensors["radon_1day_avg"]
    else:
        radon_1day = None
        logger.warning("radon_1day_avg sensor data not found in device sensors")
    if "radon_week_avg" in sensors:
        radon_week = sensors["radon_week_avg"]
    else:
        radon_week = None
        logger.warning("radon_week_avg sensor data not found in device sensors")
    if "radon_year_avg" in sensors:
        radon_year = sensors["radon_year_avg"]
    else:
        radon_year = None
        logger.warning("radon_year_avg sensor data not found in device sensors")
    if "temperature" in sensors:
        temperature = sensors["temperature"]
    else:
        temperature = None
        logger.warning("temperature sensor data not found in device sensors")
    if "humidity" in sensors:
        relative_humidity = sensors["humidity"]
    else:
        relative_humidity = None
        logger.warning("relative_humidity sensor data not found in device sensors")

    persistent_storage.write_radon_data(timestamp,
                                        radon_1day,
                                        radon_week,
                                        radon_year,
                                        temperature,
                                        relative_humidity)
    local_time = timestamp.astimezone().strftime('%d/%m/%Y, %H:%M:%S')
    print(f'Timestamp: {local_time}, Radon 1day: {radon_1day:.1f} Bq/m3, '
          f'week: {radon_week:.1f} Bq/m3, year {radon_year:.1f} Bq/m3, '
          f'temperature {temperature:.1f} C, relative humidity {relative_humidity:.1f} %', flush=True)


async def monitor_loop(address: str, interval: float, timeout: float):
    backoff = 5.0
    max_backoff = 300.0
    while True:
        try:
            device = await read_device_once(address, timeout, True, logger)
            if device is None:
                raise ConnectionError("Failed to read device data")
            save_radon_data(device)
            backoff = 5.0
        except UnsupportedDeviceError:
            logger.error("Unsupported Airthings device at %s", address)
        except Exception as exc:  # broad but we want monitor to keep running
            # If the task is being cancelled, let the CancelledError propagate
            if isinstance(exc, asyncio.CancelledError):
                raise

            # Prefer to treat DisconnectedError (from the parser) as an informational
            # transient disconnect rather than an unexpected crash. The exception
            # class may not be importable, so check by name as a fallback.
            if DisconnectedError is not None and isinstance(exc, DisconnectedError):
                logger.info("Disconnected from %s", address)
            else:
                logger.exception("Error reading %s", address)

            # exponential backoff on repeated failures
            await asyncio.sleep(backoff)
            backoff = min(max_backoff, backoff * 2)
            continue

        # Wait for the configured interval
        await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(monitor_loop(device_mac,
                            AIRTHINGS_SLEEP_DURATION_SECONDS,
                            AIRTHINGS_SCAN_TIMEOUT_SECONDS))
