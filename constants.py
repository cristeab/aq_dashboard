#!/usr/bin/env python3

import pandas as pd


SLEEP_DURATION_SECONDS = 3
AIRTHINGS_SLEEP_DURATION_SECONDS = 300
AIRTHINGS_SCAN_TIMEOUT_SECONDS = 8

def normalize_and_format_pandas_timestamp(timestamp):
    """expects as input a Pandas Timestamp object, e.g. pd.Timestamp.now(tz='UTC')"""
    if timestamp.tzinfo is None or timestamp.tz is None:
        timestamp = timestamp.tz_localize('UTC')
    timestamp = timestamp.to_pydatetime()
    return timestamp.astimezone().strftime('%d/%m/%Y, %H:%M:%S')
