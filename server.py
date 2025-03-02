#!/usr/bin/env python3

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from influxdb_client import InfluxDBClient
import asyncio
import json
import os
import sys
from plantower.persistent_storage import PersistentStorage
from fastapi.websockets import WebSocketDisconnect


token = os.environ.get("INFLUX_TOKEN")
if not token:
    print("Error: INFLUX_TOKEN environment variable is not set.")
    sys.exit(1)

app = FastAPI()

# Serve static files (HTML, JS, CSS)
app.mount("/static", StaticFiles(directory="static"), name="static")

# InfluxDB connection
storage = PersistentStorage()

@app.get("/", response_class=HTMLResponse)
async def root():
    with open("static/index.html", "r") as file:
        return file.read()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    print('Waiting for connections...')
    await websocket.accept()
    print('Connected')
    try:
        while True:
            # Query latest data from InfluxDB
            query = f'from(bucket:"{aqi_bucket}") |> range(start: -1m) |> last()'
            result = client.query_api().query(query)
            
            # Process and send data
            data = process_influxdb_result(result)
            await websocket.send_json(data)
            
            # Wait before sending next update
            await asyncio.sleep(3)
    except WebSocketDisconnect:
        print("Client disconnected")

def process_influxdb_result(result):
    print(result)
    # Process InfluxDB result and return as JSON-serializable dict
    # Implement this based on your data structure
    pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8888, ssl_keyfile="key.pem", ssl_certfile="cert.pem")
