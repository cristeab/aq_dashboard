#!/usr/bin/env python3
"""
Shared helpers for the mocked sensor workers.

Each mock_*.py script replaces one hardware worker (dust_sensor.py,
ambient_sensor.py, ...) and writes plausible values into the database through
the very same PersistentStorage API, so the web server cannot tell the
difference.

Events such as cooking or room occupancy are derived from the wall clock, so
that the independent mock processes produce correlated data (e.g. PM, VOC,
CO and noise rise together while "cooking").
"""

import argparse
import math
import os
import random
import signal
import sys
import time
from datetime import datetime, timezone

# Make the project modules (persistent_storage, constants, ...) importable
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from constants import SLEEP_DURATION_SECONDS, format_local_timestamp  # noqa: E402
from persistent_storage import PersistentStorage  # noqa: E402

# A "cooking" event of COOKING_DURATION_SEC starts every COOKING_PERIOD_SEC
COOKING_PERIOD_SEC = 15 * 60
COOKING_DURATION_SEC = 4 * 60
# Room occupancy cycle driving CO2: people present, then window opened
OCCUPANCY_PERIOD_SEC = 30 * 60


class SmoothSignal:
    """Mean reverting random walk (discrete Ornstein-Uhlenbeck process)
    producing smooth, sensor-like noise around a (possibly moving) target."""

    def __init__(self, initial, volatility, reversion=0.1, minimum=None, maximum=None):
        self.value = float(initial)
        self.volatility = volatility
        self.reversion = reversion
        self.minimum = minimum
        self.maximum = maximum

    def next(self, target):
        self.value += self.reversion * (target - self.value) + random.gauss(0.0, self.volatility)
        if self.minimum is not None:
            self.value = max(self.minimum, self.value)
        if self.maximum is not None:
            self.value = min(self.maximum, self.value)
        return self.value


def cooking_intensity(now=None):
    """0..1 intensity of the periodic cooking event: fast rise, slow decay
    for a few minutes after the event (particles and gases linger)."""
    now = time.time() if now is None else now
    phase = now % COOKING_PERIOD_SEC
    if phase < COOKING_DURATION_SEC:
        return min(1.0, phase / 60.0)  # ramps up within one minute
    return math.exp(-(phase - COOKING_DURATION_SEC) / 120.0)  # decays with a 2 min time constant


def occupancy_factor(now=None):
    """0..1 ramp: CO2 accumulates while the room is occupied (first 80% of
    the cycle) and drops quickly when the window is opened."""
    now = time.time() if now is None else now
    # the room is aired (or empty) every night: the CO2 level comes down to the outdoor level,
    # as the automatic self-calibration of the SCD41 and the sensor validation expect
    if 3 <= datetime.fromtimestamp(now).hour < 5:
        return 0.0
    phase = (now % OCCUPANCY_PERIOD_SEC) / OCCUPANCY_PERIOD_SEC
    if phase < 0.8:
        return phase / 0.8
    return max(0.0, 1.0 - (phase - 0.8) / 0.08)


def daylight_factor(now=None):
    """0..1 bell shaped daylight curve based on the local time of day."""
    local = datetime.fromtimestamp(time.time() if now is None else now).astimezone()
    hour = local.hour + local.minute / 60.0
    if 6.0 <= hour <= 20.0:
        return math.sin(math.pi * (hour - 6.0) / 14.0)
    return 0.0


def utc_now():
    return datetime.now(timezone.utc)


def parse_args(description, default_interval=SLEEP_DURATION_SECONDS, extra=None):
    parser = argparse.ArgumentParser(description=description)
    if extra is not None:
        extra(parser)
    parser.add_argument("-i", "--interval", type=float, default=default_interval,
                        help=f"seconds between two samples (default: {default_interval})")
    parser.add_argument("-s", "--seed", type=int, default=None,
                        help="random seed for reproducible data")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="do not print the samples to the standard output")
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be positive")
    if args.seed is not None:
        random.seed(args.seed)
    return args


def run_periodically(args, sample_once):
    """Calls sample_once(storage, timestamp) every args.interval seconds until
    SIGINT/SIGTERM. sample_once returns the text line to print."""
    stop = {"requested": False}

    def request_stop(signum, frame):
        stop["requested"] = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    storage = PersistentStorage()
    try:
        while not stop["requested"]:
            started = time.monotonic()
            timestamp = utc_now()
            line = sample_once(storage, timestamp)
            if line and not args.quiet:
                print(f"Timestamp: {format_local_timestamp(timestamp)}, {line}", flush=True)
            # sleep in small steps so that a stop request is honoured quickly
            deadline = started + args.interval
            while not stop["requested"] and time.monotonic() < deadline:
                time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))
    finally:
        storage.close()
