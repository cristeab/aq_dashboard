#!/usr/bin/env python3
"""Mock of noise_sensor.py: ReSpeaker Lite microphone array sound pressure level."""

import random

from mock_common import SmoothSignal, cooking_intensity, parse_args, run_periodically


def main():
    args = parse_args("Mocked noise sensor (replaces noise_sensor.py)")
    background = SmoothSignal(initial=32.0, volatility=0.6, reversion=0.15, minimum=18.0)
    baseline = 30.0

    def sample_once(storage, timestamp):
        level = background.next(32.0) + 20.0 * cooking_intensity()  # kitchen hood, dishes
        is_transient = random.random() < 0.03  # door slam, voices
        if is_transient:
            level += random.uniform(10.0, 25.0)
        level = round(level, 1)
        diagnostics = {
            "la90_raw": round(background.value - 3.0, 1),
            "baseline": baseline,
            "offset": 0.0,
            "offset_saturation_pct": 0.0,
            "is_transient": is_transient,
            "in_quiet_hours": False,
            "night_reference": None,
            "is_night_anomaly": False,
        }
        storage.write_sound_pressure_level(timestamp, level, diagnostics)
        return f"Noise level: {level:.1f} dB"

    run_periodically(args, sample_once)


if __name__ == "__main__":
    main()
