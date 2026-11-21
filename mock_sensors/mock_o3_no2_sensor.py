#!/usr/bin/env python3
"""Mock of o3_no2_sensor.py: Renesas ZMOD4510 O3 and NO2 concentrations (ppb)."""

from mock_common import SmoothSignal, cooking_intensity, parse_args, run_periodically


def main():
    args = parse_args("Mocked ZMOD4510 O3/NO2 sensor (replaces o3_no2_sensor.py)")
    o3 = SmoothSignal(initial=18.0, volatility=0.4, reversion=0.05, minimum=0.0)
    no2 = SmoothSignal(initial=6.0, volatility=0.3, reversion=0.05, minimum=0.0)

    def sample_once(storage, timestamp):
        cooking = cooking_intensity()
        o3_ppb = o3.next(18.0 - 6.0 * cooking)     # NO from the stove consumes O3
        no2_ppb = no2.next(6.0 + 22.0 * cooking)
        # ZMOD4510 AQI outputs (EPA scale), approximated from the dominant gas
        epa_aqi = round(max(o3_ppb * 50.0 / 54.0, no2_ppb * 50.0 / 53.0))
        fast_aqi = epa_aqi
        storage.write_zmod4510_data(timestamp, o3_ppb, no2_ppb, fast_aqi, epa_aqi)
        return f"O3: {o3_ppb:.3f} ppb, NO2: {no2_ppb:.3f} ppb, Fast AQI: {fast_aqi}, EPA AQI: {epa_aqi}"

    run_periodically(args, sample_once)


if __name__ == "__main__":
    main()
