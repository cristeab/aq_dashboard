#!/usr/bin/env python3
"""Mock of co_sensor.py: Winsen ZE07-CO carbon monoxide (ppm, 0.1 ppm resolution)."""

from mock_common import SmoothSignal, cooking_intensity, parse_args, run_periodically


def main():
    args = parse_args("Mocked ZE07-CO sensor (replaces co_sensor.py)")
    co = SmoothSignal(initial=0.8, volatility=0.08, reversion=0.1, minimum=0.0)

    def sample_once(storage, timestamp):
        co_ppm = round(co.next(0.8 + 14.0 * cooking_intensity()), 1)  # gas stove
        storage.write_co_data(timestamp, co_ppm)
        return f"CO: {co_ppm:.1f} PPM"

    run_periodically(args, sample_once)


if __name__ == "__main__":
    main()
