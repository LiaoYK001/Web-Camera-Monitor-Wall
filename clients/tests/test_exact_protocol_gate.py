#!/usr/bin/env python3
"""Ensure private protocol evidence never places endpoints in process arguments."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("run-exact-protocol-gate.py")
SPEC = importlib.util.spec_from_file_location("exact_protocol_gate", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ExactProtocolGateTests(unittest.TestCase):
    def test_private_endpoints_are_memory_only_child_environment_values(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as binary:
            binary_path = Path(binary.name)
        self.addCleanup(binary_path.unlink, missing_ok=True)
        endpoints = {
            environment_name: f"https://private-{index}.invalid/media?token=private-{index}"
            for index, (_, _, _, environment_name) in enumerate(MODULE.PROBES)
        }
        completed = mock.Mock(returncode=0, stdout=json.dumps({
            "result": "passed", "decoder": "fixture", "hardwareDecode": True,
            "framesDecoded": 300, "framesDropped": 0,
        }) + "\n", stderr="")
        with mock.patch.dict(os.environ, endpoints, clear=True), \
             mock.patch.object(MODULE.subprocess, "run", return_value=completed) as runner, \
             mock.patch.object(MODULE.sys, "argv", [str(SCRIPT), str(binary_path)]), \
             mock.patch("builtins.print"):
            self.assertEqual(MODULE.main(), 0)
        self.assertEqual(runner.call_count, len(MODULE.PROBES))
        for invocation, endpoint in zip(runner.call_args_list, endpoints.values(), strict=True):
            arguments = invocation.args[0]
            child_environment = invocation.kwargs["env"]
            self.assertNotIn(endpoint, arguments)
            self.assertEqual(child_environment["WEBOBS_PROBE_ENDPOINT"], endpoint)
            self.assertFalse(any(key.startswith("WEBOBS_PRIVATE_") for key in child_environment))


if __name__ == "__main__":
    unittest.main()
