#!/usr/bin/env python3

from datetime import datetime, timezone


SLEEP_DURATION_SECONDS = 3
AIRTHINGS_SLEEP_DURATION_SECONDS = 300
AIRTHINGS_SCAN_TIMEOUT_SECONDS = 8

def format_local_timestamp(timestamp: datetime) -> str:
    """Formats a datetime in the local time zone, e.g. '31/12/2025, 23:59:59'.
    Naive datetimes are interpreted as UTC."""
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone().strftime('%d/%m/%Y, %H:%M:%S')
