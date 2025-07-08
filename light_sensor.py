#!/usr/bin/env python3

import board
import busio
import adafruit_ltr390
from persistent_storage import PersistentStorage
from datetime import datetime, timezone
import time
from constants import SLEEP_DURATION_SECONDS


i2c = busio.I2C(board.SCL, board.SDA)
ltr = adafruit_ltr390.LTR390(i2c)
persistent_storage = PersistentStorage()

while True:
    timestamp = datetime.now(timezone.utc)
    visible_light_lux = ltr.lux
    uv_index = ltr.uvi
    persistent_storage.write_light_data(timestamp, visible_light_lux, uv_index)
    
    local_time = timestamp.astimezone().strftime('%d/%m/%Y, %H:%M:%S')
    print(f'Timestamp: {local_time}, Visible Light: {visible_light_lux:.1f} lux, UV Index: {uv_index:.1f}', flush=True)
    time.sleep(SLEEP_DURATION_SECONDS)
