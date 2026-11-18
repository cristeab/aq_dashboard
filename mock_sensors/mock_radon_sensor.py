#!/usr/bin/env python3
"""Mock of radon_sensor.py: Airthings Corentium Home 2 radon averages (Bq/m3,
integers), temperature and relative humidity. The real device is polled
every 5 minutes over Bluetooth LE."""

from mock_common import SmoothSignal, parse_args, run_periodically
from constants import AIRTHINGS_SLEEP_DURATION_SECONDS  # importable once mock_common set sys.path


def main():
    args = parse_args("Mocked Airthings radon sensor (replaces radon_sensor.py)",
                      default_interval=AIRTHINGS_SLEEP_DURATION_SECONDS)
    day = SmoothSignal(initial=70.0, volatility=6.0, reversion=0.1, minimum=0.0)
    week = SmoothSignal(initial=65.0, volatility=1.0, reversion=0.05, minimum=0.0)
    year = SmoothSignal(initial=60.0, volatility=0.1, reversion=0.01, minimum=0.0)
    temperature = SmoothSignal(initial=21.8, volatility=0.05, reversion=0.05)
    humidity = SmoothSignal(initial=46.0, volatility=0.3, reversion=0.05, minimum=15.0, maximum=90.0)

    def sample_once(storage, timestamp):
        radon_1day = round(day.next(70.0))
        radon_week = round(week.next(65.0))
        radon_year = round(year.next(60.0))
        t = temperature.next(21.8)
        rh = humidity.next(46.0)
        storage.write_radon_data(timestamp, radon_1day, radon_week, radon_year, t, rh)
        return (f"Radon 1day: {radon_1day} Bq/m3, week: {radon_week} Bq/m3, year {radon_year} Bq/m3, "
                f"temperature {t:.1f} C, relative humidity {rh:.1f} %")

    run_periodically(args, sample_once)


if __name__ == "__main__":
    main()
