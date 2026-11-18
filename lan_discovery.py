#!/usr/bin/env python3
"""
Discovery of the air quality servers on the local network with mDNS / DNS-SD
(Zeroconf, "Bonjour"): the web server advertises itself as an "_http._tcp" or
"_https._tcp" service with the TXT records product=aq_dashboard and path=<URL
path>, so that it can be found by any DNS-SD browser (phones, computers) and
by this script:

    ./lan_discovery.py            lists the air quality servers of the LAN

On the Raspberry Pi, the Avahi daemon can advertise the service instead
(services/avahi/aq_dashboard.service, see INSTALL.md); the web server then
does not need to advertise itself (option --advertise of aq_dashboard.py).
Needs the zeroconf package.
"""

import argparse
import ipaddress
import socket
import time
from typing import Dict, List, Optional

PRODUCT = "aq_dashboard"
SERVICE_TYPES = ("_https._tcp.local.", "_http._tcp.local.")


def _local_addresses() -> List[str]:
    """IPv4 addresses of this host (without loopback unless it is the only one)."""
    addresses = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addresses.add(info[4][0])
    except socket.gaierror:
        pass
    try:  # address of the interface of the default route
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # documentation address, nothing is sent
            addresses.add(s.getsockname()[0])
    except OSError:
        pass
    public = sorted(a for a in addresses if not ipaddress.ip_address(a).is_loopback)
    return public or ["127.0.0.1"]


class Advertiser:
    """Advertises the dashboard while the web server runs."""

    def __init__(self, port: int, path: str = "/", https: bool = False, name: Optional[str] = None,
                 addresses: Optional[List[str]] = None, logger=None):
        from zeroconf import ServiceInfo, Zeroconf  # optional dependency
        self._logger = logger
        host = socket.gethostname().split(".")[0]
        service_type = SERVICE_TYPES[0] if https else SERVICE_TYPES[1]
        self.name = f"{name or 'Air Quality Dashboard'} ({host})"
        self.addresses = addresses or _local_addresses()
        self._zeroconf = Zeroconf(interfaces=self.addresses)
        self._info = ServiceInfo(
            service_type, f"{self.name}.{service_type}",
            addresses=[socket.inet_aton(a) for a in self.addresses], port=port,
            properties={"product": PRODUCT, "path": path}, server=f"{host}.local.")

    def start(self):
        self._zeroconf.register_service(self._info, allow_name_change=True)
        if self._logger:
            self._logger.info(f"Advertised on the LAN as '{self.name}' ({', '.join(self.addresses)})")

    def stop(self):
        self._zeroconf.unregister_service(self._info)
        self._zeroconf.close()


def discover(timeout: float = 3.0, interfaces=None) -> List[Dict]:
    """Air quality servers found on the LAN: [{name, url, addresses, port, path}]."""
    from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

    found: Dict[str, Dict] = {}

    class Listener(ServiceListener):
        def add_service(self, zc, service_type, name):
            info = zc.get_service_info(service_type, name, timeout=int(timeout * 1000))
            if info is None:
                return
            properties = {k.decode(): (v or b"").decode() for k, v in info.properties.items()}
            if properties.get("product") != PRODUCT:
                return
            scheme = "https" if service_type.startswith("_https") else "http"
            addresses = info.parsed_addresses()
            host = addresses[0] if addresses else (info.server or "").rstrip(".")
            port = "" if (scheme, info.port) in (("https", 443), ("http", 80)) else f":{info.port}"
            found[name] = {"name": name.split("._")[0], "url": f"{scheme}://{host}{port}{properties.get('path', '/')}",
                           "addresses": addresses, "port": info.port, "path": properties.get("path", "/"),
                           "server": (info.server or "").rstrip(".")}

        update_service = add_service

        def remove_service(self, zc, service_type, name):
            pass

    zeroconf = Zeroconf(interfaces=interfaces) if interfaces else Zeroconf()
    try:
        browsers = [ServiceBrowser(zeroconf, service_type, Listener()) for service_type in SERVICE_TYPES]
        time.sleep(timeout)
        for browser in browsers:
            browser.cancel()
    finally:
        zeroconf.close()
    return sorted(found.values(), key=lambda s: s["name"])


def main():
    parser = argparse.ArgumentParser(description="Lists the air quality servers of the local network")
    parser.add_argument("--timeout", type=float, default=3.0, help="seconds to wait for answers (default: 3)")
    args = parser.parse_args()
    servers = discover(args.timeout)
    if not servers:
        print("No air quality server found on the local network")
    for server in servers:
        print(f"{server['name']}: {server['url']}  (host {server['server']}, {', '.join(server['addresses'])})")


if __name__ == "__main__":
    main()
