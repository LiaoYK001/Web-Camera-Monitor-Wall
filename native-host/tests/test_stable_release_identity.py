#!/usr/bin/env python3
"""Stable Windows identity is a recorded acceptance, never a version number.

Feature releases map to the two-part Tag while the installer keeps the three-part
version. Candidates, development builds and unqualified manifests must stay
outside the stable updater feed.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECEIPT = "docs/qualification/windows-v5.1-release-2026-11-18.json"


def load():
    specification = importlib.util.spec_from_file_location(
        "stable_release_identity", ROOT / "native-host/scripts/release_policy.py")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def accepted_manifest(version="5.1.0"):
    return {"version": version, "productIntegration": True, "installationQualified": True,
            "legacyUpgradeQualified": True, "fullFeatureMigrationQualified": True,
            "obsCommit": "fb4d98bf88fae5fc85cb11fc57f7c5e309282194"}


def refuses(call, expectation):
    try:
        call()
    except ValueError as error:
        assert expectation in str(error), f"unexpected rejection text: {error}"
        return
    raise AssertionError(f"stable identity accepted: {expectation}")


def exercise():
    policy = load()
    assert policy.tag_for_version("5.1.0") == "v5.1"
    assert policy.tag_for_version("5.0.0") == "v5.0"
    assert policy.tag_for_version("5.1.2") == "v5.1.2"
    assert policy.tag_for_version("4.5.0") == "v4.5"
    assert policy.tag_for_version("5.1.0-rc.25") == "v5.1.0-rc.25"
    for unpublishable in ("5.1.0-dev.3", "5.1", "5.1.0-rc", ""):
        refuses(lambda version=unpublishable: policy.tag_for_version(version), "no publishable release Tag")

    manifest = accepted_manifest()
    policy.configure_stable(manifest, qualification_receipt=RECEIPT)
    assert policy.delivery(manifest) == policy.STABLE_PROFILE
    assert manifest["releaseTag"] == "v5.1"
    assert manifest["stableUpdaterEnabled"] is True
    assert manifest["candidate"] is False
    assert manifest["publicationForbidden"] is False
    assert manifest["qualificationReceipt"] == RECEIPT
    copied = policy.copy_delivery(manifest)
    assert copied["stableUpdaterEnabled"] is True and copied["legacyUpgradeQualified"] is True
    assert copied["fullFeatureMigrationQualified"] is True and copied["candidate"] is False

    refuses(lambda: policy.configure_stable(accepted_manifest("5.1.0-rc.1"),
        qualification_receipt=RECEIPT), "three-part without a suffix")
    refuses(lambda: policy.configure_stable(accepted_manifest(), qualification_receipt="short"),
        "bounded qualification receipt")
    incomplete = {"version": "5.1.0", "productIntegration": True, "installationQualified": True,
                  "fullFeatureMigrationQualified": True}
    refuses(lambda: policy.configure_stable(incomplete, qualification_receipt=RECEIPT),
        "recorded upgrade and migration acceptance")
    uninstalled = accepted_manifest()
    uninstalled["installationQualified"] = False
    refuses(lambda: policy.delivery({**uninstalled, **policy.STABLE_FIELDS,
        "qualificationReceipt": RECEIPT}), "install acceptance")
    forged = accepted_manifest()
    forged.update(policy.STABLE_FIELDS)
    forged["qualificationReceipt"] = RECEIPT
    assert policy.delivery(forged) == policy.STABLE_PROFILE, "explicit accepted fields remain readable"
    forged["stableUpdaterEnabled"] = False
    refuses(lambda: policy.delivery(forged), "invalid stable release identity")

    candidate = {"version": "5.1.0-rc.25", "productIntegration": True}
    policy.configure_complete(candidate)
    assert policy.delivery(candidate) == policy.COMPLETE_PROFILE
    assert candidate["stableUpdaterEnabled"] is False
    assert policy.copy_delivery(candidate)["candidate"] is True

    internal = {"version": "5.1.0-dev.4", "publicationForbidden": True}
    assert policy.delivery(internal) == "internal"
    assert policy.copy_delivery(internal) == {"publicationForbidden": True}
    print("PASS stable identity requires recorded acceptance; Tag mapping keeps feature, patch and rc rules")


if __name__ == "__main__":
    exercise()
