#!/usr/bin/bash

services=("dust_sensor" "ambient_sensor" "noise_sensor" "aq_dashboard" "light_sensor" "carbon_dioxide_sensor" "voc_nox_sensor" "pressure_temp_sensor" "o3_no2_sensor" "co_sensor" "radon_sensor")
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
}

# Help is available without root privileges.
if [ $# -eq 0 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    usage
    exit 0
fi

if (( EUID != 0 )); then
    echo "You must be root to run this script." >&2
    exit 1
fi

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

# Parse the first argument
while getopts ":hiusqrt" opt; do
    case $opt in
        h)
            usage
            ;;
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
