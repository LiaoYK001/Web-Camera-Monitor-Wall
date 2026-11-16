#!/usr/bin/env python3
"""Complete candidate identity stays separate from internal and v4.5 previews."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load():
    specification = importlib.util.spec_from_file_location(
        "complete_release_policy", ROOT / "native-host/scripts/release_policy.py")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def exercise():
    policy = load()
    manifest = {"version": "5.0.0-rc.1", "productIntegration": True,
                "obsCommit": "fb4d98bf88fae5fc85cb11fc57f7c5e309282194"}
    policy.configure_complete(manifest)
    assert policy.delivery(manifest) == policy.COMPLETE_PROFILE
    assert manifest["publicationForbidden"] is False
    assert manifest["stableUpdaterEnabled"] is False
    assert manifest["fullFeatureMigrationQualified"] is False
    assert manifest["dataProfile"] == "Native"
    assert policy.copy_delivery(manifest)["candidate"] is True
    for invalid in ("5.0.0", "5.0.0-dev.1", "5.0.0-rc", "5.1.0-rc.1"):
        candidate = {"version": invalid, "productIntegration": True}
        try:
            policy.configure_complete(candidate)
        except ValueError:
            pass
        else:
            raise AssertionError("complete identity accepted an invalid candidate version")
    internal = {"version": "5.0.0-dev.1", "publicationForbidden": True}
    assert policy.delivery(internal) == "internal"
    assert policy.copy_delivery(internal) == {"publicationForbidden": True}
    print("PASS complete candidate identity, data root, feed policy and invalid-version rejection")


if __name__ == "__main__":
    exercise()
