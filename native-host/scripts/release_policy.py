"""Explicit, scoped delivery identity; it never qualifies complete migration."""
import re

PREVIEW_VERSION = "4.5.0"
PREVIEW_PROFILE = "native-monitor-preview"
COMPLETE_PROFILE = "native-complete-candidate"
COMPLETE_FIELDS = {"releaseProfile": COMPLETE_PROFILE, "publicationForbidden": False,
                   "stableUpdaterEnabled": False, "legacyUpgradeQualified": False,
                   "fullFeatureMigrationQualified": False, "dataProfile": "Native",
                   "candidate": True}
STABLE_PROFILE = "native-complete-stable"
# A stable Windows package advertises the updater feed, so it is only a valid
# delivery identity when the upgrade and full-feature migration acceptance were
# actually recorded. The policy never promotes a candidate by itself.
STABLE_FIELDS = {"releaseProfile": STABLE_PROFILE, "publicationForbidden": False,
                 "stableUpdaterEnabled": True, "dataProfile": "Native", "candidate": False}
STABLE_QUALIFIED_FIELDS = {"legacyUpgradeQualified", "fullFeatureMigrationQualified"}
PREVIEW_FIELDS = {"releaseProfile": PREVIEW_PROFILE, "publicationForbidden": False,
                  "stableUpdaterEnabled": False, "legacyUpgradeQualified": False,
                  "fullFeatureMigrationQualified": False, "dataProfile": "NativePreview"}


def tag_for_version(version):
    """Map an application/installer version to its immutable release Tag.

    Repository rule: a feature release publishes the two-part Tag while the
    application and installer keep the three-part version (``5.1.0`` -> ``v5.1``);
    a patch release keeps the full Tag (``5.1.2`` -> ``v5.1.2``); an internal
    candidate keeps its rc suffix (``5.1.0-rc.25`` -> ``v5.1.0-rc.25``); and a
    development build has no publishable Tag at all.
    """
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:-rc\.([0-9]+))?", version)
    if not match:
        raise ValueError("version has no publishable release Tag")
    major, minor, patch, candidate = match.groups()
    if candidate is not None:
        return f"v{major}.{minor}.{patch}-rc.{candidate}"
    return f"v{major}.{minor}" if patch == "0" else f"v{major}.{minor}.{patch}"


def delivery(manifest):
    if not isinstance(manifest, dict):
        raise ValueError("invalid native delivery identity")
    if manifest.get("releaseProfile") == STABLE_PROFILE:
        if not re.fullmatch(r"\d+\.\d+\.\d+", manifest.get("version", "")):
            raise ValueError("stable native release requires a three-part version without a suffix")
        if any(manifest.get(key) is not True for key in STABLE_QUALIFIED_FIELDS):
            raise ValueError("stable identity requires recorded upgrade and migration acceptance")
        receipt = manifest.get("qualificationReceipt")
        if not isinstance(receipt, str) or not 12 <= len(receipt) <= 512:
            raise ValueError("stable identity requires a bounded qualification receipt location")
        if any(manifest.get(key) is not True for key in ("productIntegration", "installationQualified")):
            raise ValueError("stable identity requires the integrated product and install acceptance")
        if any(type(manifest.get(key)) is not type(value) or manifest.get(key) != value
               for key, value in STABLE_FIELDS.items()):
            raise ValueError("invalid stable release identity")
        return STABLE_PROFILE
    if manifest.get("releaseProfile") == COMPLETE_PROFILE:
        if not re.fullmatch(r"5\.[01]\.0-rc\.[0-9]+", manifest.get("version", "")):
            raise ValueError("complete candidate identity requires 5.0.0-rc.N or 5.1.0-rc.N")
        if any(type(manifest.get(key)) is not type(value) or manifest.get(key) != value
               for key, value in COMPLETE_FIELDS.items()):
            raise ValueError("invalid complete candidate identity")
        return COMPLETE_PROFILE
    if manifest.get("releaseProfile") is not None:
        if manifest.get("version") != PREVIEW_VERSION or any(
                type(manifest.get(key)) is not type(value) or manifest.get(key) != value
                for key, value in PREVIEW_FIELDS.items()):
            raise ValueError("invalid explicitly authorized preview identity")
        return PREVIEW_PROFILE
    if manifest.get("publicationForbidden") is not True or not re.fullmatch(
            r"\d+\.\d+\.\d+-dev\.[0-9A-Za-z.-]+", manifest.get("version", "")):
        raise ValueError("internal native builds must remain publication-forbidden")
    return "internal"


def configure_preview(manifest):
    if manifest.get("version") != PREVIEW_VERSION or manifest.get("productIntegration") is not True:
        raise ValueError("only the authorized v4.5 authenticated monitor preview may use this profile")
    manifest.update(PREVIEW_FIELDS)
    manifest.update(qualification="Native monitor preview only; complete features, legacy migration and OBS parity unqualified",
                    profile="%LOCALAPPDATA%/WebOBS/NativePreview; retained on uninstall")
    delivery(manifest)


def configure_complete(manifest):
    if not re.fullmatch(r"5\.[01]\.0-rc\.[0-9]+", manifest.get("version", "")):
        raise ValueError("complete candidate version must be 5.0.0-rc.N or 5.1.0-rc.N")
    if manifest.get("productIntegration") is not True:
        raise ValueError("complete candidate requires the integrated product")
    manifest.update(COMPLETE_FIELDS)
    manifest.update(qualification="complete candidate; target-machine media, migration and OBS parity acceptance still required",
                    profile="%LOCALAPPDATA%/WebOBS/Native; retained on uninstall")
    delivery(manifest)


def copy_delivery(manifest):
    profile = delivery(manifest)
    if profile == PREVIEW_PROFILE:
        return dict(PREVIEW_FIELDS)
    if profile == COMPLETE_PROFILE:
        return dict(COMPLETE_FIELDS)
    if profile == STABLE_PROFILE:
        return {**STABLE_FIELDS,
                "legacyUpgradeQualified": manifest["legacyUpgradeQualified"],
                "fullFeatureMigrationQualified": manifest["fullFeatureMigrationQualified"],
                "qualificationReceipt": manifest["qualificationReceipt"]}
    return {"publicationForbidden": True}


def configure_stable(manifest, *, qualification_receipt):
    """Record the stable delivery identity for an already-accepted release.

    Callers must pass the location of the actual acceptance receipt. This never
    infers qualification from a version number and never touches a candidate.
    """
    if not re.fullmatch(r"\d+\.\d+\.\d+", manifest.get("version", "")):
        raise ValueError("stable release version must be three-part without a suffix")
    if manifest.get("productIntegration") is not True:
        raise ValueError("stable release requires the integrated product")
    if not isinstance(qualification_receipt, str) or not 12 <= len(qualification_receipt) <= 512:
        raise ValueError("stable release requires a bounded qualification receipt location")
    manifest.update(STABLE_FIELDS)
    manifest.update(qualificationReceipt=qualification_receipt,
                    legacyUpgradeQualified=manifest.get("legacyUpgradeQualified") is True,
                    fullFeatureMigrationQualified=manifest.get("fullFeatureMigrationQualified") is True,
                    installationQualified=manifest.get("installationQualified") is True,
                    releaseTag=tag_for_version(manifest["version"]),
                    qualification="stable Windows x64 release; only platforms listed in the receipt are accepted",
                    profile="%LOCALAPPDATA%/WebOBS/Native; retained on uninstall")
    delivery(manifest)
