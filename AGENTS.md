# Repository Guidelines

## Project Structure & Module Organization

The repository is a Raspberry Pi air-quality monitoring system. The Python entry points in the root (`aq_dashboard.py` and `*_sensor.py`) run the web server and individual sensor workers. Shared logic lives in modules such as `persistent_storage.py`, `constants.py`, and `logger_configurator.py`; the dashboard also has profile/engine modules and `tests/`. `static/` contains the browser UI, translations, and styles; `profiles/` contains configurable AQI, CO2, noise, and comfort profiles; and `docs/` contains diagrams. Hardware-specific integrations are grouped under `bosh_bme68x/`, `noise_detector/`, `plantower/`, `winsen_ze07co/`, and `renesas_zmod4510/`. Deployment assets are in `services/`, including systemd, Avahi, and Nginx configuration.

## Build, Test, and Development Commands

Set up the Python environment before running application code:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd renesas_zmod4510 && pip install .
```

Run the dashboard locally with `INFLUXDB3_AUTH_TOKEN=<token> ./aq_dashboard.py`. Sensor workers are executable scripts; for example, `./dust_sensor.py /dev/ttyUSB1 /dev/ttyUSB2`. Use `services/manage_services.sh` for service installation and control. Validate the reverse proxy configuration with `sudo nginx -t`.

The native ZMOD4510 component can be built with `cmake -S renesas_zmod4510 -B renesas_zmod4510/build` followed by `cmake --build renesas_zmod4510/build`.

Install development dependencies with `pip install -r requirements-dev.txt`. Run the ported unit tests with `python3 -m pytest -q tests`; the hardware utility tests under `plantower/` are not part of this suite.

## Coding Style & Naming Conventions

Use four spaces in Python and follow readable `snake_case` names for modules, functions, and variables. Keep sensor workers focused on hardware acquisition and persistence, and reuse shared configuration/storage helpers. Preserve the existing executable-script style and add logging through the project’s logging utilities. C code should use the existing header/source organization and project naming patterns.

## Testing Guidelines

Tests use pytest and cover the dashboard engines, authentication, profiles, storage-backed history, and FastAPI settings endpoints. There is no coverage threshold. Before submitting changes, run `python3 -m pytest -q tests` and build the ZMOD4510 component when its C/C++ or packaging code changes. For hardware-facing changes, perform a targeted run with the relevant device or service and verify logs and InfluxDB writes.

## Commit & Pull Request Guidelines

Recent commits use short, imperative descriptions (for example, `Widen notification panel` and `Optimize translation loading with dynamic language files`). Keep commits focused and describe the user-visible or hardware effect. Pull requests should explain the affected sensor/UI/service, list validation commands and hardware assumptions, link the related issue when applicable, and include screenshots for dashboard or notification changes.

## Security & Configuration Tips

Never commit InfluxDB tokens, device MAC addresses, certificates, or private configuration. Use environment variables and `/etc/default/aq_dashboard.env` for deployment secrets. Treat device paths and systemd/Nginx/Avahi changes as host-specific, and review service permissions before enabling automatic restarts. Production sensor data remains in InfluxDB; the storage adapter’s temporary-path mode is for isolated tests.
