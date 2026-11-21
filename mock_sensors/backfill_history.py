#!/usr/bin/env python3
"""
Writes synthetic past samples of the pollutants (PM, O3, NO2, CO) and of the
ambient sensor, so that the averages needed by the air quality index profiles
(NowCast 12 h, 8 h and 24 h means) are available immediately instead of after
hours of running the mocked sensors. The same signal models as the mocked
sensors are used, including the periodic cooking events. Run it before
starting the mocked sensors (run_mock_system.py --backfill-hours does that).
"""

import argparse
import random
import time
from datetime import datetime, timezone

from mock_common import PersistentStorage, SmoothSignal, cooking_intensity, occupancy_factor
from mock_dust_sensor import FAULTS, faulty_reading, make_sample

SAMPLE_PERIOD_SEC = 30


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hours", type=float, default=24, help="hours of history to write (default: 24)")
    parser.add_argument("-s", "--seed", type=int, default=None, help="random seed for reproducible data")
    parser.add_argument("--sensor-fault", choices=("none", "temperature_drift", "co2_low"), default="none",
                        help="fault for the validation of the sensors: temperature_drift makes the BME688 read 3 °C more "
                             "during the last 4 days (needs --hours 216 or more), co2_low makes the SCD41 read 150 ppm "
                             "too low (needs 7 days)")
    parser.add_argument("--dust-fault", choices=FAULTS, default="none",
                        help="fault of the second dust sensor: 'drift' makes it read 20 %% more every day during "
                             "the last 4 days (needs --hours 216 or more), the other faults affect the last 4 hours "
                             "(disagree: 8 hours)")
    args = parser.parse_args()
    if not 0 < args.hours <= 24 * 30:
        parser.error("--hours must be between 0 and 720")
    if args.seed is not None:
        random.seed(args.seed)

    storage = PersistentStorage()
    end = time.time()
    start = end - args.hours * 3600

    pm = SmoothSignal(initial=6.0, volatility=0.25, reversion=0.05, minimum=1.0)
    o3 = SmoothSignal(initial=18.0, volatility=0.4, reversion=0.05, minimum=0.0)
    no2 = SmoothSignal(initial=6.0, volatility=0.3, reversion=0.05, minimum=0.0)
    co = SmoothSignal(initial=0.8, volatility=0.08, reversion=0.1, minimum=0.0)
    co2 = SmoothSignal(initial=550.0, volatility=6.0, reversion=0.1, minimum=400.0)
    noise = SmoothSignal(initial=32.0, volatility=0.6, reversion=0.15, minimum=18.0)
    pressure = SmoothSignal(initial=1013.0, volatility=0.05, reversion=0.005, minimum=950.0, maximum=1050.0)
    temperature = SmoothSignal(initial=22.0, volatility=0.03, reversion=0.02)
    humidity = SmoothSignal(initial=45.0, volatility=0.15, reversion=0.03, minimum=15.0, maximum=90.0)

    count = 0
    t = start
    with storage.transaction():
        while t < end:
            timestamp = datetime.fromtimestamp(t, tz=timezone.utc)
            cooking = cooking_intensity(t)
            pm25 = pm.next(6.0) + 45.0 * cooking
            values = [pm25 * gain * random.uniform(0.97, 1.03) for gain in (1.0, 1.06)]
            age_hours = (end - t) / 3600
            if args.dust_fault == "drift" and age_hours < 96:
                values[1] = faulty_reading("drift", values[1], gain=1 + 0.2 * (96 - age_hours) / 24)
            elif args.dust_fault != "none" and age_hours < (8 if args.dust_fault == "disagree" else 4):
                values[1] = faulty_reading(args.dust_fault, values[1])
            for i, value in enumerate(values):
                if value is not None:
                    storage.write_pm(i, make_sample(timestamp, value))
            storage.write_zmod4510_data(timestamp, o3.next(18.0 - 6.0 * cooking), no2.next(6.0 + 22.0 * cooking), 0, 0)
            storage.write_co_data(timestamp, round(co.next(0.8 + 14.0 * cooking), 1))
            t_c, rh = temperature.next(22.0 + 1.5 * cooking), humidity.next(45.0 + 12.0 * cooking)
            p_hpa = pressure.next(1013.0)
            bme_offset = 3.0 if args.sensor_fault == "temperature_drift" and age_hours < 96 else 0.0
            # the sensors read slightly differently (self-heating, placement)
            storage.write_ambient_data(timestamp, t_c + 0.6 + bme_offset, 120000, rh, p_hpa, 50.0)
            co2_ppm = round(co2.next(480.0 + 900.0 * occupancy_factor(t))) - (150 if args.sensor_fault == "co2_low" else 0)
            storage.write_co2_data(timestamp, co2_ppm, t_c + 0.3, rh - 1.5)
            storage.write_bmp390l_data(timestamp, t_c, p_hpa - 0.4, 100.0)
            storage.write_sound_pressure_level(timestamp, round(noise.next(32.0) + 20.0 * cooking, 1))
            count += 1
            t += SAMPLE_PERIOD_SEC
    print(f"Wrote {count} samples per sensor ({args.hours:g} h, every {SAMPLE_PERIOD_SEC} s) into {storage.db_path}")
    storage.close()


if __name__ == "__main__":
    main()
