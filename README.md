# Air Quality Monitoring Kit

## Introduction

The [**software component**](INSTALL.md) of the kit includes a web server based on FastAPI Python package for displaying in real time the Air Quality Index (AQI),
as well as the particle concentration for different particle diameters. Other air pollutants (Total Volatile Organic Compounds, Nitrate Oxides, Carbon Dioxide, etc) and
environmental parameters (Temperature, Pressure, Relative Humidity, Noise Level, etc) are also shown. The data is read from different sensors and stored into a local database
before being delivered over websockets periodically to the web page shown in a web browser.

```mermaid
flowchart TB
    subgraph SENS["Sensors (Hardware)"]
        direction TB
        s1["2x PMSA003<br>(Dust)"]
        s2["ReSpeaker Lite<br>(Noise)"]
        s3["BME688<br>(Temp/Humidity/<br>Pressure/Gas)"]
        s4["LTR390<br>(Light/UV)"]
        s5["SCD41<br>(CO2)"]
        sdots["⋮"]
    end

    subgraph WK["Workers (one process per sensor)"]
        direction TB
        w1[dust_sensor.py]
        w2[noise_sensor.py]
        w3[ambient_sensor.py]
        w4[light_sensor.py]
        w5[carbon_dioxide_sensor.py]
        wdots["⋮"]
    end

    subgraph DB["InfluxDB"]
      dustdb[("dust")]
      sounddb[("sound")]
      climatedb[("climate")]
      lightdb[("light")]
      gasdb[("gas")]
    end

    s1 --> w1
    s2 --> w2
    s3 --> w3
    s4 --> w4
    s5 --> w5

    w1 --> dustdb
    w2 --> sounddb
    w3 --> climatedb
    w4 --> lightdb
    w5 --> gasdb

    dustdb --> ws["Web Server<br>(aq_dashboard.py)"]
    sounddb --> ws
    climatedb --> ws
    lightdb --> ws
    gasdb --> ws

    ws -- websockets --> rp["Reverse Proxy<br>(Nginx)"]
    rp -- websockets --> bw[Browser]

    style sdots fill:none,stroke:none
    style wdots fill:none,stroke:none
```

The [**hardware component**](BOM.md) relies on a Raspberry Pi as the main processing unit and is designed such that sensors can be easily added, replaced or removed.

## User Interface

<p align="center">
  <img src="screenshots/aq_dashboard.png" alt="Air Quality Dashboard" width="45%">
  <img src="screenshots/aq_dashboard_notifications.png" alt="Air Quality Dashboard with Notifications" width="45%">
</p>

Left Column Values (Air Pollutants):

- Nitrate Dioxide (NO2) concentration in PPB

- Ozone (O3) concentration in PPB

- Carbon Monoxide (CO) concentration in PPM

- Total Volatile Organic Compounds (TVOC) index

- Nitrate Oxides (NOx) index

- Carbon Dioxide (CO2) concentration in PPM

- Radon gas concentration in Bq/m3

Center Display:

- The timestamp expressed in local time zone of the most recent dust particle measurement

- The 10-minute Air Quality Index (AQI) - derived from dust particle measurements using a pair of PMSA007 sensors

Right Column Values (Environment Parameters):

-	Current room temperature in Celsius degrees

-	Relative humidity (amount of moisture in the air) - the normal value is around 40%

- Thom discomfort index in Celsius degrees (below 21 means no discomfort)

-	Atmospheric pressure expressed in hectoPascals

-	Noise level in the environment in decibels (around 20 dB would be very quiet)

- Visible light expressed in Lux

- UV index

Particulate Matter Measurements (from PMSA007 sensors):

-	PM1.0: Concentration of tiny particles smaller than 1.0 microns in diameter

-	PM2.5: Concentration of fine particles smaller than 2.5 microns - can penetrate deep into lungs. These values are used to compute the 10-min. AQI.

-	PM10: Concentration of particles smaller than 10 microns - includes dust, pollen, and mold

Particle Count Measurements (from PMSA007 sensors):

-	PM0.3+(0.1L): Number of particles larger than 0.3 microns per 0.1 liter of air

-	PM0.5+(0.1L) Number of particles larger than 0.5 microns per 0.1 liter of air

-	PM1.0+(0.1L) Number of particles larger than 1.0 microns per 0.1 liter of air

-	PM2.5+(0.1L): Number of particles larger than 2.5 microns per 0.1 liter of air

-	PM5.0+(0.1L) Number of particles larger than 5.0 microns per 0.1 liter of air

-	PM10+(0.1L) Number of particles larger than 10 microns per 0.1 liter of air

The notification list shown in the right image is sorted by timestamp in descending order and can be accessed by clicking the bell icon.

The UI theme can be toggled between dark and light using the button on the left of the notifications button. 

## Reference

https://cristeab.medium.com/building-an-air-quality-monitoring-station-ba74098f0528
