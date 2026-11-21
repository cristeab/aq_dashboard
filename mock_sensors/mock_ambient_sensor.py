#!/usr/bin/env python3
"""Mock of ambient_sensor.py: BME688 temperature, relative humidity, pressure,
gas resistance and BSEC IAQ, plus the Thom discomfort index."""

from mock_common import SmoothSignal, cooking_intensity, parse_args, run_periodically


def thom_discomfort_index(temperature, relative_humidity):
    """Thom (1959): DI = T - 0.55 * (1 - RH/100) * (T - 14.5)"""
    return temperature - 0.55 * (1.0 - relative_humidity / 100.0) * (temperature - 14.5)


def main():
    args = parse_args("Mocked BME688 ambient sensor (replaces ambient_sensor.py)")
    temperature = SmoothSignal(initial=22.0, volatility=0.03, reversion=0.02, minimum=10.0, maximum=35.0)
    humidity = SmoothSignal(initial=45.0, volatility=0.15, reversion=0.03, minimum=15.0, maximum=90.0)
    pressure = SmoothSignal(initial=1013.0, volatility=0.05, reversion=0.005, minimum=950.0, maximum=1050.0)
    gas = SmoothSignal(initial=120000.0, volatility=800.0, reversion=0.05, minimum=5000.0)
    iaq = SmoothSignal(initial=50.0, volatility=1.0, reversion=0.1, minimum=0.0, maximum=500.0)

    def sample_once(storage, timestamp):
        cooking = cooking_intensity()
        t = temperature.next(22.0 + 1.5 * cooking)
        rh = humidity.next(45.0 + 12.0 * cooking)  # steam from cooking
        p = pressure.next(1013.0)
        g = gas.next(120000.0 - 80000.0 * cooking)  # VOCs lower the gas resistance
        q = iaq.next(50.0 + 150.0 * cooking)
        di = thom_discomfort_index(t, rh)
        storage.write_ambient_data(timestamp, t, round(g), rh, p, q, di)
        return (f"Temperature: {t:.1f} C, Humidity: {rh:.1f} %, Pressure: {p:.1f} hPa, "
                f"Gas: {round(g)} ohms, IAQ: {q:.1f}, Thom Discomfort Index: {di:.1f}")

    run_periodically(args, sample_once)


if __name__ == "__main__":
    main()
