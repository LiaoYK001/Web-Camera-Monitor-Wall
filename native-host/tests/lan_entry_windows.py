#!/usr/bin/env python3
"""Installed-state gate for the native product LAN/Web HTTPS entry.

Runs against an installed complete runtime on Windows. A second client here is a
separate process that reaches the product through the machine's private LAN
interface over HTTPS, which proves the reverse proxy, the local CA, the allowed
origins and independent sessions. A physically separate computer on the user's
network is still required for R3-004 device qualification.

A CI Windows host can legitimately have no private IPv4 interface at all. That is
recorded honestly as ``lanHttpsQualified=false`` with a skip reason while the
entry's own contracts (setting persistence, receipt, loopback-only switch, no
listener, account sessions, restart behaviour, process cleanup) are still proved;
the gate never claims HTTPS LAN delivery it could not reach.
"""
from __future__ import annotations

import argparse
import http.client
import importlib.util
import json
import os
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_contract(runtime):
    path = runtime / "services/product/product_lan.py"
    if not path.is_file() or path.is_symlink():
        raise ValueError("installed runtime is missing the LAN entry contract")
    specification = importlib.util.spec_from_file_location("installed_product_lan", path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def read_json(path):
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 262144:
        raise ValueError("missing or invalid private state")
    return json.loads(path.read_text(encoding="utf-8"))


def wait_for(predicate, message, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(.15)
    raise AssertionError(message)


class Client:
    """One independent client session; loopback or LAN HTTPS, never both at once."""

    def __init__(self, host, port, *, secure, cafile=None):
        self.host = host
        self.port = int(port)
        self.secure = secure
        self.cafile = cafile
        self.cookie = ""

    def request(self, path, body=None, *, cookie=None, origin=None, method=None):
        headers = {"Host": f"{self.host}:{self.port}", "Content-Type": "application/json"}
        if origin is not None:
            headers["Origin"] = origin
        session = self.cookie if cookie is None else cookie
        if session:
            headers["Cookie"] = session
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        if method is None:
            method = "POST" if payload is not None else "GET"
        context = None
        if self.secure:
            context = ssl.create_default_context(cafile=self.cafile)
            # The product issues its own certificate for the private address, so
            # verification is against that root and the address itself.
            context.check_hostname = True
        connection = (http.client.HTTPSConnection(self.host, self.port, context=context, timeout=10)
            if self.secure else http.client.HTTPConnection(self.host, self.port, timeout=10))
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            text = response.read(65536).decode("utf-8", "replace")
            issued = response.getheader("Set-Cookie", "")
        finally:
            connection.close()
        if issued.startswith("webobs_session="):
            self.cookie = issued.split(";", 1)[0]
        return response.status, text


def tcp_open(address, port):
    try:
        with socket.create_connection((address, int(port)), timeout=3):
            return True
    except OSError:
        return False


def exercise(runtime, report):
    if os.name != "nt":
        raise ValueError("the LAN entry gate requires the actual Windows product runtime")
    manifest = read_json(runtime / "webobs-native-prototype.json")
    if manifest.get("productIntegration") is not True:
        raise ValueError("internal integrated product build required")
    caddy = runtime / "bin/caddy.exe"
    if not caddy.is_file():
        raise ValueError("the complete runtime must ship Caddy for the LAN entry")
    contract = load_contract(runtime)
    entry = runtime / "bin/webobs-wall.exe"
    powershell = shutil.which("pwsh")
    if not powershell:
        raise ValueError("test-side PowerShell 7 required")
    evidence = {"schema": 1, "kind": "native-lan-entry", "version": manifest["version"],
        "passed": False, "checks": [], "lastCheckpoint": "prepare",
        "remoteDeviceQualified": False, "lanHttpsQualified": False, "lanHttpsSkipReason": "",
        "addresses": [], "port": 0}
    process = None
    port = 18443 + secrets.randbelow(2000)
    account = {"username": "lan-owner", "password": secrets.token_urlsafe(24)}

    def start(profile, environment):
        nonlocal process
        previous = ""
        status_path = profile / "run/native-status.json"
        if status_path.is_file():
            previous = read_json(status_path).get("bootId", "")

        def ready():
            assert process.poll() is None, "native product entry exited during startup"
            value = read_json(status_path) if status_path.is_file() else {}
            return value if value.get("phase") == "running" and isinstance(value.get("bootId"), str) \
                and value["bootId"] != previous and re.fullmatch(r"[a-f0-9]{32}", value["bootId"]) else None
        return wait_for(ready, "native entry did not start its required services")

    def launch(profile):
        nonlocal process
        environment = dict(os.environ)
        environment["WEBOBS_PRODUCT_TEST_ROOT"] = str(profile)
        process = subprocess.Popen([str(entry)], env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return start(profile, environment)

    def stop(profile):
        nonlocal process
        if process is None:
            return
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        process = None
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            value = read_json(profile / "run/native-status.json") if (profile / "run/native-status.json").is_file() else {}
            if value.get("phase") == "stopped":
                return
            time.sleep(.2)
        raise AssertionError("the product entry did not report a normal stop")

    with tempfile.TemporaryDirectory(prefix="WebOBS 局域网入口-") as temporary:
        private = Path(temporary)
        profile = private / "profile"
        profile.mkdir()
        try:
            evidence["lastCheckpoint"] = "setting-persisted"
            setting = contract.write_setting(profile, True, port)
            assert setting["enabled"] is True and setting["port"] == port, \
                "the LAN setting did not persist for this profile"
            discovered = contract.discover_addresses()
            evidence["discoveredAddresses"] = list(discovered)
            evidence["lastCheckpoint"] = "installed-entry-started"
            status = launch(profile)
            evidence["ownerPid"] = status["ownerPid"]
            local_port = int(status["origin"].rsplit(":", 1)[1])

            def loopback():
                return Client("127.0.0.1", local_port, secure=False)

            def boot_receipt(value):
                receipt = value.get("lan") or {}
                assert receipt.get("enabled") is True, "the status receipt did not report the LAN entry"
                assert receipt.get("pendingRestart") is False, \
                    "a boot-time entry must not report a pending restart"
                assert receipt.get("switchPort"), "the private LAN switch is not listening on loopback"
                return receipt

            evidence["lastCheckpoint"] = "lan-receipt-published"
            receipt = boot_receipt(status)
            addresses = tuple(receipt.get("addresses") or ())
            assert all(url.startswith("https://") for url in receipt.get("urls") or ()), \
                "the LAN entry must publish HTTPS URLs only"

            evidence["lastCheckpoint"] = "switch-loopback-only"
            # The switch is the window's private channel: no token, no toggle, and
            # it must never answer on the LAN address the consumers use.
            switch = Client("127.0.0.1", receipt["switchPort"], secure=False)
            assert switch.request("/lan")[0] == 401, "the LAN switch answered without the host token"
            assert switch.request("/lan", {"enabled": False, "port": port})[0] == 401, \
                "the LAN switch accepted an unauthenticated toggle"
            assert tcp_open("127.0.0.1", receipt["switchPort"]), "the private switch is not on loopback"
            evidence["checks"].append("lan-switch-rejects-unauthenticated-read-and-toggle")

            evidence["lastCheckpoint"] = "status-file-reports-the-entry"
            # The installed gates and the support bundle read this file; they are
            # never given the host token the product window uses.
            published = read_json(profile / "run/native-status.json")
            assert published.get("lanSwitchPort") == receipt["switchPort"], \
                "the status file did not publish the private switch port"
            assert published.get("lan", {}).get("enabled") is True, \
                "the status file did not report the enabled LAN entry"
            assert published.get("lan", {}).get("urls") == (receipt.get("urls") or []), \
                "the status file and the switch receipt disagree about the published URLs"
            evidence["checks"].append("lan-receipt-published-for-support-diagnostics")

            evidence["lastCheckpoint"] = "account-provisioned-on-loopback"
            # The installed product starts with an empty account store; the first
            # account is created through the loopback setup endpoint, then the same
            # real account is used by every later client.
            local = loopback()
            code, body = local.request("/api/v1/auth/setup")
            assert code == 200 and json.loads(body).get("registrationOpen") is True, \
                f"the account store did not open registration on a fresh profile: {code} {body[:160]}"
            code, _ = local.request("/api/v1/auth/setup", account, origin=status["origin"])
            assert code == 201, f"the first account could not be created: {code}"
            code, _ = local.request("/api/v1/auth/login", account, origin=status["origin"])
            assert code == 200 and local.cookie, f"loopback login failed: {code}"
            code, session = local.request("/api/v1/auth/session", cookie=local.cookie,
                origin=status["origin"])
            assert code == 200 and account["username"] in session, "loopback session is not authenticated"
            code, _ = local.request("/api/v1/auth/setup", account, origin=status["origin"])
            assert code == 409, "a created account store still accepted a second first account"
            evidence["checks"].append("first-account-created-through-loopback-setup")

            if addresses:
                evidence["lanHttpsQualified"] = True
                assert contract.private_ipv4(addresses[0]), "discovered address is not private"
                assert tcp_open(addresses[0], port), \
                    "the LAN HTTPS port is not reachable on the LAN interface"
                evidence["checks"].append("lan-https-listener-reachable-on-private-interface")

                evidence["lastCheckpoint"] = "local-ca-issued"
                certificate = profile / "caddy/pki/authorities/local/root.crt"
                wait_for(lambda: certificate.is_file(), "the product local CA was not issued", timeout=30)

                evidence["lastCheckpoint"] = "lan-https-health"
                lan = Client(addresses[0], port, secure=True, cafile=certificate)
                code, body = lan.request("/api/v1/health", origin=f"https://{addresses[0]}:{port}")
                assert code == 200, f"LAN HTTPS health failed: {code} {body[:200]}"
                evidence["checks"].append("ca-verified-https-health-through-product-proxy")

                evidence["lastCheckpoint"] = "foreign-origin-rejected"
                rejected, rejected_body = lan.request("/api/v1/auth/login", account,
                    origin="http://127.0.0.1:1")
                assert rejected != 200, "a foreign Origin was accepted over the LAN entry"
                assert "session" not in rejected_body.lower(), "a rejected Origin issued account data"
                evidence["checks"].append(f"foreign-origin-rejected-{rejected}")

                evidence["lastCheckpoint"] = "lan-login-and-session"
                code, _ = lan.request("/api/v1/auth/login", account, origin=f"https://{addresses[0]}:{port}")
                assert code == 200 and lan.cookie, f"LAN HTTPS login failed: {code}"
                code, body = lan.request("/api/v1/auth/session", cookie=lan.cookie,
                    origin=f"https://{addresses[0]}:{port}")
                assert code == 200 and account["username"] in body, "LAN session is not authenticated"

                evidence["lastCheckpoint"] = "loopback-and-lan-sessions-independ"
                again = loopback()
                code, _ = again.request("/api/v1/auth/login", account, origin=status["origin"])
                assert code == 200 and again.cookie, f"loopback login failed after LAN login: {code}"
                code, _ = again.request("/api/v1/auth/session", cookie=again.cookie, origin=status["origin"])
                assert code == 200, "loopback session lost after the LAN session opened"
                code, _ = lan.request("/api/v1/auth/logout", {}, cookie=lan.cookie, method="POST",
                    origin=f"https://{addresses[0]}:{port}")
                assert code == 204, f"LAN logout did not report: {code}"
                code, _ = lan.request("/api/v1/auth/session", cookie=lan.cookie,
                    origin=f"https://{addresses[0]}:{port}")
                assert code != 200, "the closed LAN session still authenticated"
                code, _ = again.request("/api/v1/auth/session", cookie=again.cookie, origin=status["origin"])
                assert code == 200, "ending the LAN client stopped the local consumer"
                evidence["checks"].append("two-clients-share-one-product-and-exit-independently")
            else:
                # Honest degradation: this host exposes no private IPv4, so no LAN
                # HTTPS URL can exist. The entry must stay closed rather than fall
                # back to plain HTTP, and the local consumer must keep working.
                evidence["lanHttpsSkipReason"] = "no-private-ipv4-interface"
                assert receipt.get("running") is False, \
                    "a LAN entry without a private address must not start a listener"
                assert receipt.get("urls") == [], \
                    "a LAN entry without a private address published URLs"
                assert receipt.get("reason") == "lan-address-unavailable", \
                    f"unexpected LAN reason: {receipt.get('reason')}"
                assert not tcp_open("127.0.0.1", port), \
                    "the LAN port opened anyway without a private address"
                code, _ = local.request("/api/v1/auth/session", cookie=local.cookie, origin=status["origin"])
                assert code == 200, "the local consumer broke when no LAN address existed"
                evidence["checks"].append("lan-entry-stays-closed-without-a-private-address")
                print("NOTE no private IPv4 interface: LAN HTTPS is reported as not qualified")

            evidence["addresses"] = list(addresses)
            evidence["port"] = port
            evidence["urls"] = list(receipt.get("urls") or ())

            evidence["lastCheckpoint"] = "disable-and-restart-closes-listener"
            stop(profile)
            contract.write_setting(profile, False, port)
            status = launch(profile)
            disabled = status.get("lan") or {}
            assert disabled.get("enabled") is False, "the restart did not read the disabled setting"
            assert disabled.get("urls") == [], "a disabled LAN entry still published URLs"
            assert disabled.get("running") is False, "a disabled LAN entry still runs a listener"
            for address in addresses:
                assert not tcp_open(address, port), "the LAN port stayed open after disabling"
            assert not tcp_open("127.0.0.1", port), "the LAN port stayed open on loopback after disabling"
            again = loopback()
            code, _ = again.request("/api/v1/auth/login", account, origin=status["origin"])
            assert code == 200, "loopback monitoring stopped working after disabling the LAN entry"
            evidence["checks"].append("disabled-setting-restarts-without-a-listener")
            stop(profile)

            listing = subprocess.run([powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
                "Get-Process | ForEach-Object { $_.ProcessName }"], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=25)
            leftovers = {name.strip().lower() for name in listing.stdout.splitlines()} & {
                "webobs-wall", "webobsd", "obs64", "caddy", "mediamtx", "go2rtc"}
            assert not leftovers, f"product processes survived the gate: {sorted(leftovers)}"
            evidence["checks"].append("no-product-process-survives-after-exit")

            evidence["passed"] = True
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(f"PASS installed LAN entry: {len(evidence['checks'])} checks")
            return 0
        finally:
            if process is not None:
                try:
                    process.kill()
                except OSError:
                    pass
            report.parent.mkdir(parents=True, exist_ok=True)
            if not report.is_file():
                report.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        return exercise(arguments.runtime.resolve(), arguments.report.resolve())
    except (AssertionError, ValueError, OSError) as error:
        print(f"LAN entry gate failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
