#!/usr/bin/env python3
"""
Starts all mocked sensor workers and the web server, so that the dashboard
can be used without any sensor hardware. Stop everything with Ctrl+C.

By default a dedicated database (mock_sensors/mock_aq_dashboard.db) is used,
so that mocked data never ends up in the database of a real installation.
"""

import argparse
import importlib.util
import os
import signal
import subprocess
import sys
import time

MOCK_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(MOCK_DIR)
DEFAULT_DB_PATH = os.path.join(MOCK_DIR, "mock_aq_dashboard.db")

MOCK_SCRIPTS = [
    "mock_dust_sensor.py",
    "mock_noise_sensor.py",
    "mock_ambient_sensor.py",
    "mock_light_sensor.py",
    "mock_carbon_dioxide_sensor.py",
    "mock_voc_nox_sensor.py",
    "mock_o3_no2_sensor.py",
    "mock_co_sensor.py",
    "mock_radon_sensor.py",
    "mock_pressure_temp_sensor.py",
]
# Let the mocks write their first samples before the web server starts, so
# that no "missing data" notifications are raised at start-up
STARTUP_DELAY_SEC = 3


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help=f"SQLite database file (default: {DEFAULT_DB_PATH})")
    parser.add_argument("--reset-db", action="store_true", help="delete the database before starting")
    parser.add_argument("--backfill-hours", type=float, default=0, metavar="HOURS",
                        help="write HOURS of synthetic history before starting, so that the 8 h / 24 h / NowCast "
                             "averages of the air quality indices are available immediately (e.g. 24)")
    parser.add_argument("--host", default="127.0.0.1", help="web server interface (default: 127.0.0.1, "
                                                            "use 0.0.0.0 to access it from other devices)")
    parser.add_argument("--port", type=int, default=8888, help="web server port (default: 8888)")
    parser.add_argument("--dust-fault", choices=("none", "drift", "disagree", "stuck", "missing"), default="none",
                        help="simulate a fault of the second dust sensor, also in the backfilled history "
                             "(drift needs --backfill-hours 216 or more)")
    parser.add_argument("--sensor-fault", choices=("none", "temperature_drift", "co2_low"), default="none",
                        help="fault in the backfilled history for the validation of the sensors (needs --backfill-hours 216)")
    parser.add_argument("--user", default="admin:aq-demo-2024", metavar="NAME:PASSWORD",
                        help="account created in the mock database if it has none, with a default password "
                             "that must be changed after the first login (default: admin:aq-demo-2024)")
    parser.add_argument("--no-auth", action="store_true", help="disable the login (AQ_AUTH=off)")
    parser.add_argument("--advertise", action="store_true", help="advertise the dashboard on the LAN (mDNS)")
    parser.add_argument("--no-dashboard", action="store_true", help="only start the mocked sensors")
    parser.add_argument("-v", "--verbose", action="store_true", help="show the samples printed by the mocked sensors")
    parser.add_argument("--skip", nargs="*", default=[], metavar="SCRIPT",
                        help="mocked sensor scripts not to start, e.g. mock_radon_sensor.py "
                             "(useful to check the missing data notifications)")
    return parser.parse_args()


def start(name, command, env, quiet):
    stdout = subprocess.DEVNULL if quiet else None
    process = subprocess.Popen(command, cwd=PROJECT_DIR, env=env, stdout=stdout)
    print(f"Started {name} (pid {process.pid})", flush=True)
    return name, process


def create_demo_user(user: str, env):
    """Creates the login account in the mock database if there is none. Like the default password of
    a device, the password is not checked and must be changed after the first login."""
    name, _, password = user.partition(":")
    code = ("from auth import AuthManager; from persistent_storage import PersistentStorage; "
            "from logger_configurator import LoggerConfigurator as L; "
            "a = AuthManager(PersistentStorage(), L.configure_logger('MockUser'), enabled=False); import sys; "
            "sys.exit(0) if a.list_users() else a.create_user(sys.argv[1], sys.argv[2], must_change=True, check_strength=False); print('created')")
    result = subprocess.run([sys.executable, "-c", code, name, password], cwd=PROJECT_DIR, env=env,
                            capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"Cannot create the login account: {result.stderr.strip()}")
    if "created" in result.stdout:
        print(f"Login account created in the mock database: {name} / {password} "
              f"(to be changed after the first login)", flush=True)
    else:
        print("Login: use the account of the mock database (see --user when it was created)", flush=True)


def raise_keyboard_interrupt(signum, frame):
    raise KeyboardInterrupt


def stop_all(processes, timeout=10):
    for _, process in processes:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
    deadline = time.monotonic() + timeout
    for name, process in processes:
        try:
            process.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            print(f"{name} did not stop, killing it", flush=True)
            process.kill()
            process.wait()


def check_dashboard_requirements():
    missing = [m for m in ("fastapi", "uvicorn", "websockets") if importlib.util.find_spec(m) is None]
    if missing:
        sys.exit(f"Missing Python package(s) for the web server: {', '.join(missing)}. Activate the virtual "
                 f"environment or run: pip install -r requirements-dashboard.txt")


def main():
    args = parse_args()
    if not args.no_dashboard:
        check_dashboard_requirements()
    unknown = set(args.skip) - set(MOCK_SCRIPTS)
    if unknown:
        sys.exit(f"Unknown script(s) to skip: {', '.join(sorted(unknown))}")

    db_path = os.path.abspath(args.db)
    if args.reset_db:
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(db_path + suffix):
                os.remove(db_path + suffix)
    env = dict(os.environ, AQ_DB_PATH=db_path, PYTHONUNBUFFERED="1")
    if args.no_auth:
        env["AQ_AUTH"] = "off"
    print(f"Database: {db_path}", flush=True)
    if not args.no_auth and not args.no_dashboard:
        create_demo_user(args.user, env)
    if args.backfill_hours > 0:
        result = subprocess.run([sys.executable, os.path.join(MOCK_DIR, "backfill_history.py"),
                                 "--hours", str(args.backfill_hours), "--dust-fault", args.dust_fault,
                                 "--sensor-fault", args.sensor_fault], cwd=PROJECT_DIR, env=env)
        if result.returncode != 0:
            sys.exit("Backfilling the history failed")

    processes = []
    # SIGTERM (e.g. from systemd or kill) is handled like Ctrl+C
    signal.signal(signal.SIGTERM, raise_keyboard_interrupt)
    try:
        for script in MOCK_SCRIPTS:
            if script not in args.skip:
                command = [sys.executable, os.path.join(MOCK_DIR, script)]
                if script == "mock_dust_sensor.py" and args.dust_fault != "none":
                    command += ["--fault", args.dust_fault]
                processes.append(start(script, command, env, quiet=not args.verbose))
        if not args.no_dashboard:
            time.sleep(STARTUP_DELAY_SEC)
            processes.append(start("aq_dashboard.py",
                                   [sys.executable, os.path.join(PROJECT_DIR, "aq_dashboard.py"),
                                    "--host", args.host, "--port", str(args.port)] + (["--advertise"] if args.advertise else []),
                                   env, quiet=False))
            host = "localhost" if args.host in ("127.0.0.1", "0.0.0.0") else args.host
            print(f"\nDashboard: http://{host}:{args.port}/  (press Ctrl+C to stop)\n", flush=True)

        reported = set()
        while True:
            for name, process in processes:
                if process.poll() is None or name in reported:
                    continue
                reported.add(name)
                if name == "aq_dashboard.py":
                    print(f"{name} exited with code {process.returncode}, stopping everything", flush=True)
                    raise KeyboardInterrupt
                # keep going: the dashboard is expected to report the missing data
                print(f"{name} exited with code {process.returncode}", flush=True)
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        print("\nStopping...", flush=True)
        stop_all(processes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
