#!/usr/bin/env python3
"""Linux contract tests for the native product LAN/Web entry.

These exercise the persisted setting, the Caddy reverse-proxy document and the
origin policy the control server receives. Serving real LAN traffic from a
second machine is separate device evidence and is not claimed here.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "native-host/scripts"))

import product_lan


class AddressTests(unittest.TestCase):
    def test_only_private_ranges_are_accepted(self):
        for address in ("10.1.2.3", "172.16.0.9", "172.31.255.254", "192.168.4.7"):
            self.assertTrue(product_lan.private_ipv4(address), address)
        for address in ("172.15.0.1", "172.32.0.1", "1.1.1.1", "127.0.0.1", "169.254.1.1",
                        "010.1.1.1", "10.1.1", "10.1.1.256", "10.1.1.01", "", "host.local", None):
            self.assertFalse(product_lan.private_ipv4(address), address)

    def test_discovery_deduplicates_and_drops_public(self):
        self.assertEqual(product_lan.classify(["192.168.1.20", "192.168.1.20", "8.8.8.8", "10.0.0.5"]),
            ["192.168.1.20", "10.0.0.5"])
        self.assertEqual(product_lan.discover_addresses(runner=lambda: ["192.168.1.20", "bad"]),
            ["192.168.1.20"])

    def test_failed_discovery_is_not_a_public_address(self):
        self.assertEqual(product_lan.discover_addresses(runner=lambda: []), [])


class SettingTests(unittest.TestCase):
    def test_missing_file_is_disabled_with_the_locked_port(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(product_lan.read_setting(Path(temporary)),
                {"enabled": False, "port": product_lan.DEFAULT_PORT})

    def test_round_trip_and_restart_reads_the_same_entry(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(product_lan.write_setting(Path(temporary), True, 19443),
                {"enabled": True, "port": 19443})
            self.assertEqual(product_lan.read_setting(Path(temporary)), {"enabled": True, "port": 19443})
            setting = json.loads((Path(temporary) / "config/native-lan.json").read_text(encoding="utf-8"))
            self.assertEqual(setting, {"schema": 1, "enabled": True, "port": 19443})
            self.assertEqual(list((Path(temporary) / "config").glob("native-lan-*.new")), [],
                "an interrupted write must not leave a staging file behind")

    def test_rejects_out_of_range_port_and_wrong_types(self):
        with tempfile.TemporaryDirectory() as temporary:
            for enabled, port in ((True, 80), (True, 1023), (True, 65536), (True, "18443"),
                    ("true", 18443), (None, 18443)):
                with self.assertRaises(ValueError, msg=str((enabled, port))):
                    product_lan.write_setting(Path(temporary), enabled, port)

    def test_rejects_unknown_schema_fields_and_oversize(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "config"
            config.mkdir(parents=True)
            path = config / "native-lan.json"
            for value in ({"schema": 2, "enabled": True, "port": 18443},
                          {"schema": 1, "enabled": True},
                          {"schema": 1, "enabled": True, "port": 18443, "extra": 1},
                          {"schema": 1, "enabled": "yes", "port": 18443}):
                path.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaises(ValueError, msg=json.dumps(value)):
                    product_lan.read_setting(Path(temporary))
            path.write_text("x" * (product_lan.SETTING_LIMIT + 1), encoding="utf-8")
            with self.assertRaises(ValueError):
                product_lan.read_setting(Path(temporary))

    @unittest.skipIf(os.name == "nt", "POSIX symlink fixture")
    def test_refuses_a_symlinked_setting(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "config"
            config.mkdir(parents=True)
            target = Path(temporary) / "elsewhere.json"
            target.write_text(json.dumps({"schema": 1, "enabled": True, "port": 18443}), encoding="utf-8")
            (config / "native-lan.json").symlink_to(target)
            with self.assertRaises(ValueError):
                product_lan.read_setting(Path(temporary))


class CaddyTests(unittest.TestCase):
    def test_document_proxies_only_to_the_loopback_control_port(self):
        value = product_lan.caddy_configuration(["192.168.1.20", "10.0.0.5"], 18443, 55123, Path("/root/caddy"))
        self.assertIs(value["admin"]["disabled"], True)
        self.assertEqual(value["storage"], {"module": "file_system", "root": "/root/caddy"})
        server = value["apps"]["http"]["servers"]["lan"]
        self.assertEqual(server["listen"], ["192.168.1.20:18443", "10.0.0.5:18443"])
        route = server["routes"][0]
        self.assertEqual(route["match"][0]["host"], ["192.168.1.20", "10.0.0.5"])
        handle = route["handle"][0]
        self.assertEqual(handle["handler"], "reverse_proxy")
        self.assertEqual(handle["upstreams"], [{"dial": "127.0.0.1:55123"}])
        self.assertEqual(handle["headers"]["request"]["delete"],
            ["X-WebObs-Principal", "X-WebObs-Permissions", "X-WebObs-User", "Authorization-Internal"])
        self.assertIs(value["apps"]["pki"]["certificate_authorities"]["local"]["install_trust"], False)

    def test_refuses_public_addresses_and_bad_ports(self):
        for addresses in ([], ["8.8.8.8"], ["127.0.0.1"], ["192.168.1.20", "1.1.1.1"]):
            with self.assertRaises(ValueError, msg=str(addresses)):
                product_lan.caddy_configuration(addresses, 18443, 55123, Path("/root/caddy"))
        for port in (80, 1023, 65536, "18443"):
            with self.assertRaises(ValueError, msg=str(port)):
                product_lan.caddy_configuration(["192.168.1.20"], port, 55123, Path("/root/caddy"))
        with self.assertRaises(ValueError):
            product_lan.caddy_configuration(["192.168.1.20"], 18443, 80, Path("/root/caddy"))

    def test_firewall_guidance_is_display_only_and_bounded(self):
        commands = product_lan.firewall_instructions(18443, ["192.168.1.20"])
        self.assertEqual(len(commands), 1)
        self.assertTrue(commands[0].startswith("New-NetFirewallRule"))
        self.assertIn("-Profile Private", commands[0])
        self.assertIn("-RemoteAddress LocalSubnet", commands[0])
        with self.assertRaises(ValueError):
            product_lan.firewall_instructions(18443, ["8.8.8.8"])


class PlanTests(unittest.TestCase):
    def test_disabled_entry_serves_nothing(self):
        value = product_lan.plan({"enabled": False, "port": 18443}, ["192.168.1.20"], 55123, Path("/root"))
        self.assertEqual(value["urls"], [])
        self.assertIsNone(value["configuration"])
        self.assertEqual(value["reason"], "")
        self.assertEqual(product_lan.control_origins("http://127.0.0.1:55123", value),
            ["http://127.0.0.1:55123"])
        self.assertEqual(product_lan.media_origins(value), [])

    def test_enabled_without_a_private_address_reports_the_reason(self):
        value = product_lan.plan({"enabled": True, "port": 18443}, ["8.8.8.8"], 55123, Path("/root"))
        self.assertEqual(value["reason"], "lan-address-unavailable")
        self.assertIsNone(value["configuration"])
        self.assertEqual(value["urls"], [])

    def test_enabled_publishes_https_origins_for_control_and_media(self):
        value = product_lan.plan({"enabled": True, "port": 19443}, ["192.168.1.20"], 55123, Path("/root"))
        self.assertEqual(value["urls"], ["https://192.168.1.20:19443"])
        self.assertEqual(product_lan.control_origins("http://127.0.0.1:55123", value),
            ["http://127.0.0.1:55123", "https://192.168.1.20:19443"])
        self.assertEqual(product_lan.media_origins(value), ["https://192.168.1.20:19443"])
        self.assertTrue(value["certificate"].endswith("/caddy/pki/authorities/local/root.crt"))

    def test_receipt_is_bounded_and_carries_no_paths(self):
        value = product_lan.plan({"enabled": True, "port": 19443}, ["10.0.0.9"], 55123, Path("/root"))
        receipt = product_lan.status(value)
        self.assertEqual(sorted(receipt), ["addresses", "certificate", "enabled", "firewallCommands",
            "port", "reason", "urls"])
        self.assertEqual(receipt["urls"], ["https://10.0.0.9:19443"])


class SupervisorEntryTests(unittest.TestCase):
    """The supervisor side of the switch: fail closed, persist, and stay loopback."""

    def stub(self, root, addresses=(), *, reserve=None):
        import contextlib
        import threading
        import types

        import product_supervisor

        shim = types.SimpleNamespace(**{
            name: getattr(product_lan, name)
            for name in dir(product_lan) if not name.startswith("_")})
        shim.discover_addresses = lambda: list(addresses)
        supervisor = product_supervisor.ProductSupervisor.__new__(product_supervisor.ProductSupervisor)
        supervisor.root = root
        supervisor.runtime = root / "runtime"
        supervisor.environment = {}
        supervisor.resources = contextlib.ExitStack()
        supervisor.origin = "http://127.0.0.1:55123"
        supervisor.failure_reason = ""
        supervisor.stop_requested = threading.Event()
        supervisor.lan = shim
        supervisor.lan_value = shim.plan({"enabled": False, "port": product_lan.DEFAULT_PORT}, [], 0, root)
        supervisor.lan_lock = threading.Lock()
        supervisor.lan_dirty = threading.Event()
        supervisor.lan_process = None
        supervisor.lan_lease = None
        supervisor.lan_config = None
        supervisor.lan_control_port = 0
        supervisor.lan_server = None
        supervisor.token = "t" * 64
        supervisor.lan_thread = None
        if reserve is not None:
            supervisor.reserve_lan_port = reserve
        return supervisor

    def test_disabled_entry_keeps_the_loopback_origin_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            supervisor = self.stub(Path(temporary), reserve=lambda address, port: socket.socket())
            supervisor.prepare_lan(55123)
            self.assertEqual(supervisor.environment["WEBOBS_CONTROL_ALLOWED_ORIGINS"],
                "http://127.0.0.1:55123")
            self.assertNotIn("WEBOBS_PWA_MEDIA_ALLOWED_ORIGINS", supervisor.environment)
            self.assertEqual(supervisor.lan_value["urls"], [])
            self.assertFalse((Path(temporary) / "run/lan-caddy.json").exists())

    def test_malformed_setting_fails_closed_without_a_listener(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            product_lan.write_setting(root, True, 18443)
            (root / "config/native-lan.json").write_text("{ not json", encoding="utf-8")
            supervisor = self.stub(root, ["192.168.1.20"],
                reserve=lambda address, port: socket.socket())
            with self.assertRaises(ValueError):
                supervisor.prepare_lan(55123)
            self.assertEqual(supervisor.environment.get("WEBOBS_CONTROL_ALLOWED_ORIGINS"), None)
            self.assertFalse((root / "run/lan-caddy.json").exists())

    def test_enabled_entry_publishes_https_origins_and_a_loopback_proxy_document(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            product_lan.write_setting(root, True, 19443)
            supervisor = self.stub(root, ["192.168.1.20"],
                reserve=lambda address, port: socket.socket())
            supervisor.prepare_lan(55123)
            self.assertEqual(supervisor.environment["WEBOBS_CONTROL_ALLOWED_ORIGINS"],
                "http://127.0.0.1:55123,https://192.168.1.20:19443")
            self.assertEqual(supervisor.environment["WEBOBS_PWA_MEDIA_ALLOWED_ORIGINS"],
                "https://192.168.1.20:19443")
            self.assertEqual(supervisor.environment["WEBOBS_GO2RTC_WEBRTC_HOSTS"], "192.168.1.20")
            document = json.loads((root / "run/lan-caddy.json").read_text(encoding="utf-8"))
            self.assertEqual(document["apps"]["http"]["servers"]["lan"]["listen"], ["192.168.1.20:19443"])
            self.assertEqual(document["apps"]["http"]["servers"]["lan"]["routes"][0]["handle"][0]
                ["upstreams"], [{"dial": "127.0.0.1:55123"}])
            self.assertEqual(supervisor.lan_status()["urls"], ["https://192.168.1.20:19443"])
            self.assertIs(supervisor.lan_status()["running"], False)

    def test_enabled_entry_without_a_private_address_reports_the_reason(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            product_lan.write_setting(root, True, 18443)
            supervisor = self.stub(root, [], reserve=lambda address, port: socket.socket())
            supervisor.prepare_lan(55123)
            self.assertEqual(supervisor.lan_status()["reason"], "lan-address-unavailable")
            self.assertEqual(supervisor.environment["WEBOBS_CONTROL_ALLOWED_ORIGINS"],
                "http://127.0.0.1:55123")

    def test_busy_lan_port_stops_the_start_instead_of_serving_http(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            product_lan.write_setting(root, True, 19443)

            def busy(address, port):
                raise OSError("only one usage of each socket address")

            supervisor = self.stub(root, ["192.168.1.20"], reserve=busy)
            with self.assertRaises(RuntimeError):
                supervisor.prepare_lan(55123)
            self.assertEqual(supervisor.failure_reason, "lan-port-unavailable")
            self.assertFalse((root / "run/lan-caddy.json").exists())

    def test_switch_persists_the_setting_and_marks_the_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            supervisor = self.stub(Path(temporary), ["192.168.1.20"],
                reserve=lambda address, port: socket.socket())
            receipt = supervisor.request_lan(True, 19443)
            self.assertEqual(receipt["enabled"], True)
            self.assertEqual(receipt["port"], 19443)
            self.assertIs(receipt["pendingRestart"], True)
            self.assertEqual(product_lan.read_setting(supervisor.root), {"enabled": True, "port": 19443})
            with self.assertRaises(ValueError):
                supervisor.request_lan(True, 80)
            self.assertEqual(product_lan.read_setting(supervisor.root), {"enabled": True, "port": 19443})


class SwitchServerTests(unittest.TestCase):
    """The window talks to this private loopback switch with the host token."""

    def setUp(self):
        import product_supervisor

        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.supervisor = SupervisorEntryTests().stub(self.root, ["192.168.1.20"],
            reserve=lambda address, port: socket.socket())
        self.server = product_supervisor.LanControlServer(self.supervisor)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.token = {"X-WebOBS-Native-Token": self.supervisor.token}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temporary.cleanup()

    def request(self, method, path, body=None, headers=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method,
            headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def test_get_requires_the_host_token(self):
        self.assertEqual(self.request("GET", "/lan")[0], 401)
        status, value = self.request("GET", "/lan", headers=self.token)
        self.assertEqual(status, 200)
        self.assertEqual(sorted(value), ["addresses", "certificate", "enabled", "firewallCommands",
            "pendingRestart", "port", "reason", "running", "switchPort", "urls"])

    def test_unknown_path_and_unparsable_body_are_rejected(self):
        self.assertEqual(self.request("GET", "/status", headers=self.token)[0], 404)
        self.assertEqual(self.request("POST", "/lan", headers=self.token)[0], 400)
        self.assertEqual(self.request("POST", "/lan", {"enabled": True}, self.token)[0], 400)
        self.assertEqual(self.request("POST", "/lan", {"enabled": True, "port": 80}, self.token),
            (400, {"error": "invalid-setting"}))
        self.assertEqual(product_lan.read_setting(self.root),
            {"enabled": False, "port": product_lan.DEFAULT_PORT})

    def test_post_switch_and_read_back_the_same_entry(self):
        status, value = self.request("POST", "/lan", {"enabled": True, "port": 19443}, self.token)
        self.assertEqual(status, 200)
        self.assertEqual(value["urls"], ["https://192.168.1.20:19443"])
        self.assertEqual(self.request("GET", "/lan", headers=self.token)[1]["port"], 19443)
        self.assertEqual(product_lan.read_setting(self.root), {"enabled": True, "port": 19443})


if __name__ == "__main__":
    unittest.main()
