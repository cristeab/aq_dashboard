# Installation Instructions

## Software Prerequisites

- Debian 12

- An InfluxDB 3 Core database is used to store the data received from different sensors and retrieved it to be shown in a web page.
The following databases must be configured: dust, gas, climate, sound, light. A read/write access token must be configured.

- Installing lgpio Python module requires to install from sources the official lgpio C library from its GitHub repository

```bash
  wget https://github.com/joan2937/lg/archive/master.zip
  unzip master.zip
  cd lg-master
  make
  sudo make install
```

- A Python virtual environment must be setup in order to run the Python scripts:

```bash
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
```
- The Python module for ZMOD4510 O3 NO2 sensor must be added separately

```bash
  cd renesas_zmod4510
  pip install .
```

## Setup Influxdb3 Database

- Show database service status

```bash
sudo systemctl status influxdb3-core
```

- Show database service logs

```bash
sudo journalctl -fu influxdb3-core
```

- Quick fix in case the service does not start

```bash
sudo rm -rf ~/.influxdb/data/airquality/wal
sudo rm -f ~/.influxdb/data/airquality/snapshots/*
```

- Create database

```bash
  export INFLUXDB3_AUTH_TOKEN="<token>"
  influxdb3 create database <name>
```

- Show available databases:

```bash
  export INFLUXDB3_AUTH_TOKEN="<token>"
  influxdb3 show databases
```

## Start Sensor Workers

Several Python scripts must be started to read data from sensors and write the data into the database:

  - `dust_sensor.py`: Reads the particle concentration data from two PMSA003 air quality dust sensors, computes the 10 min AQI and writes it to the aqi and pm databases. The USB ports where the air quality sensors are attached must be provided as inputs.

```bash
    export INFLUXDB3_AUTH_TOKEN="<token>"
    ./dust_sensor.py /dev/ttyUSB1 /dev/ttyUSB2
```

  - `noise_sensor.py`: Reads the ambiental noise level from a 2-Mic array sensor and writes it to the database. A 30 seconds duration is used at start to calibrate the algorithm: during this duration a quiet environment is needed.

```bash
    export INFLUXDB3_AUTH_TOKEN="<token>"
    ./noise_sensor.py
```

  - `ambient_sensor.py`: Reads the temperature, the relative humididy, the pressure, the gas resistance and the indoor air quality and writes it to the database. In order to read this sensor and process raw data with BSEC library the user must install this [Python extension for BME68x](https://github.com/cristeab/bme68x-python-library).

```bash
    export INFLUXDB3_AUTH_TOKEN="<token>"
    ./ambient_sensor.py
```

- `light_sensor.py`: Reads the visible light in lux and the UV index from an LTR390 sensor.

```bash
    export INFLUXDB3_AUTH_TOKEN="<token>"
    ./light_sensor.py
```

- `carbon_dioxide_sensor.py`: Reads the CO2 level in ppm from an SCD41 sensor.

```bash
    export INFLUXDB3_AUTH_TOKEN="<token>"
    ./carbon_dioxide_sensor.py
```

- `o3_no2_sensor.py`: Reads the O3 and NO2 concentrations in ppb from a ZMOD4510 sensor.

```bash
    export INFLUXDB3_AUTH_TOKEN="<token>"
    ./o3_no2_sensor.py
```

- `co_sensor.py`: Reads the CO concentration in ppm from a ZE07 CO sensor.

```bash
    export INFLUXDB3_AUTH_TOKEN="<token>"
    ./co_sensor.py /dev/ttyACM0
```

- `voc_nox_sensor.py`: Reads the Total Volatile Organic Compounds (TVOC) index and the Nitrate Oxides (NOx) index from a Sensirion SGP41 sensor (I2C) and writes it to the database.

```bash
    export INFLUXDB3_AUTH_TOKEN="<token>"
    ./voc_nox_sensor.py
```

- `radon_sensor.py`: Reads the Radon gas concentration in Bq/m3 from an Airthings Corentium Home 2 sensor over Bluetooth Low Energy and writes it to the database. The device's Bluetooth MAC address must be provided via the `AIRTHINGS_DEVICE_MAC` environment variable.

```bash
    export INFLUXDB3_AUTH_TOKEN="<token>"
    export AIRTHINGS_DEVICE_MAC="<mac address>"
    ./radon_sensor.py
```

The scripts print in the standard output the current data read from the sensors and can be installed as services using the `services/manage_services.sh` script.
When installing the Python scripts as services, one must provide in a separate file `/etc/default/aq_dashboard.env` the database access token.
Also, in order to automatically restart the services if an error occurs, the user running the services must have rights to run "sudo systemctl restart *.service" without requiring a password.
The datasets provided by these scripts can be analyzed with the [aq_data_analysis](https://github.com/cristeab/aq_data_analysis) project.

## Configure Nginx as Reverse Proxy

On the RPi5 running Debian 12:
``` bash
sudo apt update
sudo apt install nginx -y
```

Configure default SSL Certificates
```bash
sudo apt install ssl-cert -y
sudo make-ssl-cert generate-default-snakeoil --force
```

This automatically populates the default certificates at:
- Cert: /etc/ssl/certs/ssl-cert-snakeoil.pem
- Key: /etc/ssl/private/ssl-cert-snakeoil.key

Install Nginx Configuration:
``` bash
sudo cp services/nginx_aq_dashboard.conf /etc/nginx/sites-available/aq_dashboard
sudo ln -s /etc/nginx/sites-available/aq_dashboard /etc/nginx/sites-enabled/
# Remove default site if not needed
sudo rm -f /etc/nginx/sites-enabled/default
```

Verify Nginx and Restart Services
```bash
sudo nginx -t
```

```bash
sudo systemctl restart nginx
sudo systemctl restart aq_dashboard
```

## Web Server User Interface

Start the server with:

```bash
    export INFLUXDB3_AUTH_TOKEN="<token>"
    ./aq_dashboard.py
```

Access the server at: https://\<server URL\>/aqd