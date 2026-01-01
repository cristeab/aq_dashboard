#!/usr/bin/bash

if (( EUID != 0 )); then
    echo "You must be root to run this script." >&2
    exit 1
fi

services=("air_quality" "ambient" "noise_sensor" "aq_dashboard" "light_sensor" "carbon_dioxide_sensor" "voc_nox_sensor" "pressure_sensor" "o3_no2_sensor" "co_sensor")
SERVICE_DIR=/etc/systemd/system

# Usage message
usage() {
    echo "Usage: $0 [-i] [-u] [-s] [-q] [-r] [-t]"
    echo "  -i    Install services"
    echo "  -u    Uninstall services"
    echo "  -s    Start services"
    echo "  -q    Stop services"
    echo "  -r    Restart services"
    echo "  -t    Show service status"
    exit 1
}

install() {
    echo "Installing services..."
    for file in "${services[@]}"; do
        cp ${file}.service ${SERVICE_DIR}
    done
    systemctl daemon-reload
    for file in "${services[@]}"; do
        systemctl enable ${file}.service
        systemctl start ${file}.service
    done
}

uninstall() {
    echo "Uninstalling services..."
    for file in "${services[@]}"; do
        systemctl stop ${file}.service
        systemctl disable ${file}.service
        rm ${SERVICE_DIR}/${file}.service
    done
    systemctl daemon-reload
}

start() {
    echo "Starting services..."
    for file in "${services[@]}"; do
        systemctl start ${file}.service
    done
}

stop() {
    echo "Stopping services..."
    for file in "${services[@]}"; do
        systemctl stop ${file}.service
    done
}

restart() {
    echo "Restarting services..."
    for file in "${services[@]}"; do
        systemctl restart ${file}.service
    done
}

status() {
    echo "Showing service status..."
    for file in "${services[@]}"; do
        systemctl status ${file}.service
    done
}

# Check for at least one argument
if [ $# -eq 0 ]; then
    usage
fi

# Parse the first argument
while getopts ":iusqrt" opt; do
    case $opt in
        i)
            install
            ;;
        u)
            uninstall
            ;;
        s)
            start
            ;;
        q)
            stop
            ;;
        r)
            restart
            ;;
        t)
            status
            ;;
        \?)
            echo "Invalid option: -$OPTARG"
            usage
            ;;
    esac
done
