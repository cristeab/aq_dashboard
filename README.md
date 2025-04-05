# aq_dashboard
Air Quality Dashboard

Web server based on FastAPI Python package for displaying the Air Quality Index (AQI),
as well as the particle concentration for different particle diameters. The temperature,
the humididy, the pressure, the altitude, the volatile organic components and the noise
level are also shown.
The data is delivered over websockets periodically to the web page.

Prepare Python virtual environment and activate it:

    python3 -m venv .venv
    source .venv/bin/activate

Install requirements with

    pip install -r requirements.txt

Start the server with:

    ./aq_dashboard.py

Access the server at: https://\<server URL\>:8888

![AQD](screenshots/aq_dashboard.png "Air Quality Dashboard")
