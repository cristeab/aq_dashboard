#!/usr/bin/env python3
"""Mock of pressure_temp_sensor.py: BMP390L pressure, temperature and altitude."""

from mock_common import SmoothSignal, parse_args, run_periodically

SEA_LEVEL_PRESSURE_HPA = 1013.25


def altitude_m(pressure_hpa):
    # International barometric formula, as used by the Adafruit BMP3xx driver
    return 44307.7 * (1.0 - (pressure_hpa / SEA_LEVEL_PRESSURE_HPA) ** 0.190284)


def main():
    args = parse_args("Mocked BMP390L pressure sensor (replaces pressure_temp_sensor.py)")
    pressure = SmoothSignal(initial=1001.0, volatility=0.05, reversion=0.005, minimum=950.0, maximum=1050.0)
    temperature = SmoothSignal(initial=22.2, volatility=0.03, reversion=0.02)

    def sample_once(storage, timestamp):
        p = pressure.next(1001.0)
        t = temperature.next(22.2)
        alt = altitude_m(p)
        storage.write_bmp390l_data(timestamp, t, p, alt)
        return f"Pressure: {p:6.2f} hPa, Temperature: {t:5.2f} C, Altitude: {alt:6.2f} m"

    run_periodically(args, sample_once)


if __name__ == "__main__":
    main()
