#!/usr/bin/env python3
"""Mock of light_sensor.py: LTR390 visible light (lux) and UV index,
following the local time of day."""

from mock_common import SmoothSignal, daylight_factor, parse_args, run_periodically


def main():
    args = parse_args("Mocked LTR390 light sensor (replaces light_sensor.py)")
    clouds = SmoothSignal(initial=1.0, volatility=0.02, reversion=0.05, minimum=0.4, maximum=1.2)

    def sample_once(storage, timestamp):
        daylight = daylight_factor() * clouds.next(1.0)
        lux = 3.0 + 320.0 * daylight  # indoor, near a window; small lamp at night
        uv_index = 0.6 * daylight     # most UV is blocked by the window glass
        storage.write_light_data(timestamp, lux, uv_index)
        return f"Visible Light: {lux:.1f} lux, UV Index: {uv_index:.1f}"

    run_periodically(args, sample_once)


if __name__ == "__main__":
    main()
