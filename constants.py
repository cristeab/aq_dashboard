#!/usr/bin/env python3

SLEEP_DURATION_SECONDS = 3

def normalize_and_format_time(timestamp):
    """Normalize and format timestamp to UTC."""
    if timestamp.tzinfo is None or timestamp.tz is None:
        timestamp = timestamp.tz_localize('UTC')
    timestamp = timestamp.to_pydatetime()
    return timestamp.astimezone().strftime('%d/%m/%Y, %H:%M:%S')
