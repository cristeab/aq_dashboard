# Air Quality Dashboard

Web server based on FastAPI Python package for displaying the Air Quality Index (AQI),
as well as the particle concentration for different particle diameters. The temperature, the humididy, the pressure, the altitude, the volatile organic components and the noise level are also shown. The data is delivered over websockets periodically to the web page.

## Prerequisites

- Debian 12

- An InfluxDB database is used to store the data received from different sensors and retrieved it to be shown in a web page.
The following buckets must be configured: aqi, pm, noise, temperature. A read/write access token must be configured.

- A Python virtual environment must be setup in order to run the Python scripts:

```bash
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
```

## Get Sensor Data

Several Python scripts must be started to read data from sensors and write the data into the database:

  - `air_quality.py`: Reads the particle concentration data from two air quality sensors, computes the 10 min AQI and writes it to the database (aqi and pm buckets)

```bash
    export INFLUX_TOKEN="<token>"
    ./air_quality.py /dev/ttyUSB1 /dev/ttyUSB2
```

  - `noise_level.py`: Reads the noise level and writes it to the database (noise bucket)

```bash
    export INFLUX_TOKEN="<token>"
    ./noise_level.py --port /dev/ttyACM0
```

  - `ambient_monitor.py`: Reads the temperature, the humididy, the pressure, the altitude and the volatile organic components and writes it to the database (temperature bucket). This script must be started as root.

```bash
    export INFLUX_TOKEN="<token>"
    ./ambient_monitor.py
```

The scripts print in the standard output the current data read from the sensors.

## Start the Web Server

Start the server with:

```bash
    export INFLUX_TOKEN="<token>"
    ./aq_dashboard.py
```

Access the server at: https://\<server URL\>:8888

![AQD](screenshots/aq_dashboard.png "Air Quality Dashboard")

## Bill of Materials

| Quantity | Item |
|--------------|----------|
| **Air Quality Sensors** | |
| 2            | PLANTOWER PMSA003 Laser PM2.5 dust sensor |
| 2            | Adapter 4P G7A to G135 and 4pin 2.54mm conversion module G7 G10 G1 G3 G5 laser PM2.5 sensor exchange PLANTOWER |
| 2            | TZT FT232BL FT232RL Basic Breakout Board FTDI FT232 USB TO TTL 5V 3.3V Debugger Download Cable To Serial Adapter Module |
| **Noise Sensor** | |
| 1        | 30db~120db Decibel meter detection noise generator module noise sensor tester RS485 industrial grade sound sensor TTL 5V |
| 1        | CP2102 USB 2.0 to UART TTL 5PIN Connector Module Serial Converter |
| **Temperature/Pressure/Humidity Sensor** | |
| 1        | BME688 Environment Sensor Module Temperature/Humidity/Pressure/Gas AI Smart I2C |
| 1        | FT232H High Speed Multifunction USB to JTAG UART FIFO SPI I2C |
| 1        | JST1.0 SH1.0 4pin cable with socket male head Dupont wire For STEMMA QT For QWIIC |