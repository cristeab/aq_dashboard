#!/usr/bin/env python3

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import asyncio
from plantower.persistent_storage import PersistentStorage
from fastapi.websockets import WebSocketDisconnect


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
    await websocket.accept()
    try:
        while True:
            # Query latest data from InfluxDB
            aqi_data = storage.read_aqi()
            if "time" not in aqi_data:
                continue
            if "pm25_cf1_aqi" not in aqi_data:
                continue
            data = {
                "timestamp": aqi_data["time"],
                "aqi": aqi_data["pm25_cf1_aqi"]
            }
            for i in range(2):
                pm_data = storage.read_pm(i)
                data = data | {
                    "pm10_" + str(i): pm_data["pm10_cf1"],
                    "pm25_" + str(i): pm_data["pm25_cf1"],
                    "pm100_" + str(i): pm_data["pm100_cf1"],
                    "pm03plus_" + str(i): pm_data["gr03um"],
                    "pm05plus_" + str(i): pm_data["gr05um"],
                    "pm10plus_" + str(i): pm_data["gr10um"],
                    "pm25plus_" + str(i): pm_data["gr25um"],
                    "pm50plus_" + str(i): pm_data["gr50um"],
                    "pm100plus_" + str(i): pm_data["gr100um"]
                }
            data = data | {
                            "temperature": 0,
                            "humidity": 0
                    }

            # Send data to client
            await websocket.send_json(data)
            
            # Wait before sending next update
            await asyncio.sleep(3)
    except WebSocketDisconnect:
        print("Client disconnected")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8888, ssl_keyfile="key.pem", ssl_certfile="cert.pem")
