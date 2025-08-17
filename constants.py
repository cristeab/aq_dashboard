#!/usr/bin/env python3

import pandas as pd


SLEEP_DURATION_SECONDS = 3

# expects as input a Pandas Timestamp object, e.g. pandas.Timestamp.now()
def normalize_and_format_pandas_timestamp(timestamp=None):
    """Normalize and format timestamp to UTC."""
    if timestamp is None:
        timestamp = pd.Timestamp.now()
    if timestamp.tzinfo is None or timestamp.tz is None:
        timestamp = timestamp.tz_localize('UTC')
    timestamp = timestamp.to_pydatetime()
    return timestamp.astimezone().strftime('%d/%m/%Y, %H:%M:%S')
