#!/usr/bin/env python3
"""Private LAN/Web entry contract for the native product supervisor.

Pure contract functions plus the persisted setting file. The supervisor owns the
process lifecycle; this module never opens a socket and never trusts an address
that is not a private IPv4 literal. The behaviour mirrors the retired Electron
supervisor contract (desktop/src/lan.mjs) so the same HTTPS reverse proxy,
certificate authority and origin policy apply to the single native product host.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

SCHEMA = 1
DEFAULT_PORT = 18443
MIN_PORT = 1024
MAX_PORT = 65535
SETTING_LIMIT = 4096

# Display-only PowerShell guidance. The supervisor never writes firewall rules:
# the account owner's administrator decides whether to run them.
FIREWALL_LIMIT = 8


def private_ipv4(address) -> bool:
    """True only for the RFC 1918 ranges the LAN entry may publish."""
    if not isinstance(address, str):
        return False
    parts = address.split(".")
    if len(parts) != 4:
        return False
    try:
        octets = [int(part) for part in parts]
    except ValueError:
        return False
    if any(part < 0 or part > 255 for part in octets) or any(
            len(part) > 3 or (len(part) > 1 and part.startswith("0")) for part in parts):
        return False
    first, second = octets[0], octets[1]
    return first == 10 or (first == 172 and 16 <= second <= 31) or (first == 192 and second == 168)


def classify(addresses) -> list[str]:
    """Deduplicate in first-seen order and drop anything that is not private."""
    result = []
    for address in addresses:
        if private_ipv4(address) and address not in result:
            result.append(address)
    return result


def discover_addresses(runner=None) -> list[str]:
    """Private IPv4 addresses of this machine.

    Windows is the only delivered native host; the enumeration deliberately
    avoids a locale-dependent parser. Tests inject ``runner`` because the
    supervisor must stay importable on Linux development machines.
    """
    if runner is None:
        if os.name != "nt":
            return []
        runner = _powershell_addresses
    return classify(runner())


def _powershell_addresses() -> list[str]:
    command = ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
        "[System.Net.Sockets.Socket]::ObtainLocalIPAddresses($true, $true) -join ','"]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    return classify(line.strip() for line in completed.stdout.replace(",", "\n").splitlines())


def _valid_port(port) -> bool:
    return type(port) is int and MIN_PORT <= port <= MAX_PORT


def read_setting(root: Path) -> dict:
    """Return the persisted LAN setting; a missing file is a disabled entry.

    Anything malformed raises instead of silently re-enabling an HTTPS listener.
    """
    path = Path(root) / "config/native-lan.json"
    if path.is_symlink() or (path.exists() and getattr(path.lstat(), "st_file_attributes", 0) & 0x400):
        raise ValueError("LAN setting must not be a link")
    if not path.exists():
        return {"enabled": False, "port": DEFAULT_PORT}
    if not path.is_file() or path.stat().st_size > SETTING_LIMIT:
        raise ValueError("LAN setting is invalid")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != {"schema", "enabled", "port"}:
        raise ValueError("LAN setting is invalid")
    if type(value["schema"]) is not int or value["schema"] != SCHEMA:
        raise ValueError("LAN setting is invalid")
    if type(value["enabled"]) is not bool or not _valid_port(value["port"]):
        raise ValueError("LAN setting is invalid")
    return {"enabled": value["enabled"], "port": value["port"]}


def write_setting(root: Path, enabled: bool, port: int) -> dict:
    """Persist the setting atomically so a crash cannot half-enable the entry."""
    if type(enabled) is not bool or not _valid_port(port):
        raise ValueError("LAN setting is invalid")
    directory = Path(root) / "config"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "native-lan.json"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix="native-lan-",
                suffix=".new", dir=directory, delete=False) as output:
            temporary = Path(output.name)
            json.dump({"schema": SCHEMA, "enabled": enabled, "port": port}, output)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
        if os.name != "nt":
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"enabled": enabled, "port": port}


def caddy_configuration(addresses, port: int, control_port: int, storage: Path) -> dict:
    """Caddy v2 JSON: HTTPS on each private address, reverse proxy to loopback.

    Admin stays disabled and the certificate authority stays private to the
    product data root. Product credential headers are removed before proxying.
    """
    if not addresses or any(not private_ipv4(address) for address in addresses):
        raise ValueError("No private LAN address is available")
    if not _valid_port(port) or not _valid_port(control_port):
        raise ValueError("LAN or control port is invalid")
    return {
        "admin": {"disabled": True, "config": {"persist": False}},
        "storage": {"module": "file_system", "root": str(storage)},
        "apps": {
            "pki": {"certificate_authorities": {
                "local": {"name": "WebOBS Local CA", "install_trust": False}}},
            "tls": {
                "certificates": {"automate": list(addresses)},
                "automation": {"policies": [
                    {"subjects": list(addresses), "issuers": [{"module": "internal"}]}]}},
            "http": {"servers": {"lan": {
                "listen": [f"{address}:{port}" for address in addresses],
                "automatic_https": {"disable_redirects": True},
                "routes": [{
                    "match": [{"host": list(addresses)}],
                    "handle": [{
                        "handler": "reverse_proxy",
                        "upstreams": [{"dial": f"127.0.0.1:{control_port}"}],
                        "headers": {"request": {"delete": ["X-WebObs-Principal",
                            "X-WebObs-Permissions", "X-WebObs-User", "Authorization-Internal"]}}}]}]}}},
        },
    }


def firewall_instructions(port: int, addresses) -> list[str]:
    """Display-only guidance; the product never applies firewall rules itself."""
    if not _valid_port(port) or not addresses or any(not private_ipv4(a) for a in addresses):
        raise ValueError("LAN port or address is invalid")
    return [f"New-NetFirewallRule -DisplayName 'WebOBS LAN HTTPS' -Direction Inbound -Action Allow "
            f"-Profile Private -LocalPort {port} -Protocol TCP -RemoteAddress LocalSubnet"]


def plan(setting: dict, addresses, control_port: int, root: Path) -> dict:
    """Project the persisted setting onto what this boot can actually serve."""
    enabled = setting["enabled"]
    port = setting["port"]
    serving = classify(addresses) if enabled else []
    value = {"schema": SCHEMA, "enabled": enabled, "serving": serving, "port": port,
             "urls": [f"https://{address}:{port}" for address in serving],
             "certificate": str(Path(root) / "caddy/pki/authorities/local/root.crt") if serving else "",
             "configuration": None, "firewallCommands": [], "reason": ""}
    if not enabled:
        return value
    if not serving:
        value["reason"] = "lan-address-unavailable"
        return value
    if not _valid_port(control_port):
        value["reason"] = "lan-control-port-invalid"
        return value
    value["configuration"] = caddy_configuration(serving, port, control_port, Path(root) / "caddy")
    value["firewallCommands"] = firewall_instructions(port, serving)
    return value


def control_origins(loopback_origin: str, value: dict) -> list[str]:
    """The control server accepts its loopback origin plus every LAN HTTPS origin."""
    origins = [loopback_origin]
    origins.extend(value["urls"])
    return origins


def media_origins(value: dict) -> list[str]:
    """Media fetch origins are HTTPS-only; the loopback http origin stays control-only."""
    return list(value["urls"])


def status(value: dict) -> dict:
    """Bounded receipt view: URLs, certificate path and display-only guidance."""
    return {"enabled": value["enabled"], "port": value["port"], "addresses": list(value["serving"]),
            "urls": list(value["urls"]), "certificate": value["certificate"],
            "reason": value["reason"], "firewallCommands": list(value["firewallCommands"])[:FIREWALL_LIMIT]}
