#!/usr/bin/env python3
"""Mock of voc_nox_sensor.py: Sensirion SGP41 VOC and NOx indices (integers).
The VOC index averages 100 and the NOx index 1 in clean air."""

from mock_common import SmoothSignal, cooking_intensity, parse_args, run_periodically


def main():
    args = parse_args("Mocked SGP41 VOC/NOx sensor (replaces voc_nox_sensor.py)")
    voc = SmoothSignal(initial=100.0, volatility=2.0, reversion=0.1, minimum=1.0, maximum=500.0)
    nox = SmoothSignal(initial=1.0, volatility=0.3, reversion=0.2, minimum=1.0, maximum=500.0)

    def sample_once(storage, timestamp):
        cooking = cooking_intensity()
        voc_index = round(voc.next(100.0 + 180.0 * cooking))
        nox_index = round(nox.next(1.0 + 120.0 * cooking))  # gas stove
        storage.write_sgp41_data(timestamp, voc_index, nox_index)
        return f"VOC index: {voc_index}, NOx index: {nox_index}"

    run_periodically(args, sample_once)


if __name__ == "__main__":
    main()
