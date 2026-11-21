#!/usr/bin/env python3
"""Mock of carbon_dioxide_sensor.py: SCD41 CO2 (ppm, integer), temperature and
relative humidity. CO2 builds up while the room is occupied and drops when the
window is opened."""

from mock_common import SmoothSignal, occupancy_factor, parse_args, run_periodically


def main():
    args = parse_args("Mocked SCD41 CO2 sensor (replaces carbon_dioxide_sensor.py)")
    co2 = SmoothSignal(initial=550.0, volatility=6.0, reversion=0.1, minimum=400.0)
    temperature = SmoothSignal(initial=22.4, volatility=0.03, reversion=0.02)
    humidity = SmoothSignal(initial=44.0, volatility=0.15, reversion=0.03, minimum=15.0, maximum=90.0)

    def sample_once(storage, timestamp):
        value = round(co2.next(480.0 + 900.0 * occupancy_factor()))
        t = temperature.next(22.4)
        rh = humidity.next(44.0)
        storage.write_co2_data(timestamp, value, t, rh)
        return f"CO2: {value} ppm, Temperature: {t:.1f} C, Humidity: {rh:.1f} %RH"

    run_periodically(args, sample_once)


if __name__ == "__main__":
    main()
