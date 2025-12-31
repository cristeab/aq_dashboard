#!/usr/bin/env python3
"""
Periodically read an Airthings device by Bluetooth address and save sensor data into db.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from datetime import datetime
from typing import Optional

from bleak import BleakScanner

from airthings_ble import AirthingsBluetoothDeviceData, UnsupportedDeviceError
# Try to import DisconnectedError for finer-grained handling; fall back to None
try:
    from airthings_ble.parser import DisconnectedError  # type: ignore
except Exception:
    DisconnectedError = None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Periodically read an Airthings device")
    p.add_argument("--address", "-a", required=True, help="Bluetooth address to connect to")
    p.add_argument("--interval", "-i", type=float, default=60.0, help="Seconds between reads")
    p.add_argument("--timeout", "-t", type=float, default=8.0, help="Scan timeout in seconds")
    p.add_argument("--imperial", action="store_true", help="Show non-metric units when applicable")
    p.add_argument("--debug", action="store_true", help="Enable debug logging")
    p.add_argument("--log-file", help="Optional log file path")
    return p.parse_args()


def print_device(device) -> None:
    print("---")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Device: {device.name} @ {device.address}")
    for k, v in sorted(device.sensors.items()):
        print(f"  {k}: {v}")


async def find_device_by_address(address: str, timeout: float):
    devices = await BleakScanner.discover(timeout=timeout)
    for d in devices:
        if d.address.lower() == address.lower():
            return d
    return None


async def read_device_once(address: str, timeout: float, is_metric: bool, logger: logging.Logger):
    target = await find_device_by_address(address, timeout)
    if target is None:
        raise ConnectionError(f"Device with address {address} not found during scan")

    client = AirthingsBluetoothDeviceData(logger=logger, is_metric=is_metric)
    device = await client.update_device(target)
    return device


async def monitor_loop(address: str, interval: float, timeout: float, is_metric: bool, logger: logging.Logger, stop_event: asyncio.Event):
    backoff = 5.0
    max_backoff = 300.0
    while not stop_event.is_set():
        try:
            device = await read_device_once(address, timeout, is_metric, logger)
            print_device(device)
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

        # Wait for the configured interval, but exit early if stopped
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue


def setup_logging(debug: bool, log_file: Optional[str]) -> None:
    handlers = [logging.StreamHandler(sys.stdout)]
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )
    if log_file:
        fh = logging.FileHandler(log_file)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger().addHandler(fh)


def main() -> int:
    args = parse_args()
    setup_logging(args.debug, args.log_file)
    logger = logging.getLogger("airthings_ble_monitor")

    stop_event = asyncio.Event()

    def _signal_handler(signum, frame):
        logger.info("Received signal %s, stopping monitor...", signum)
        # signal handlers run in main thread; set event via loop.call_soon_threadsafe
        loop = asyncio.get_event_loop()
        loop.call_soon_threadsafe(stop_event.set)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        asyncio.run(monitor_loop(args.address, args.interval, args.timeout, not args.imperial, logger, stop_event))
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt, exiting")
    except Exception:
        logger.exception("Unhandled exception in monitor")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
