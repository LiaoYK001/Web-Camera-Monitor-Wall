"""Explicit, scoped delivery identity; it never qualifies complete migration."""
import re

PREVIEW_VERSION = "4.5.0"
PREVIEW_PROFILE = "native-monitor-preview"
COMPLETE_PROFILE = "native-complete-candidate"
COMPLETE_FIELDS = {"releaseProfile": COMPLETE_PROFILE, "publicationForbidden": False,
                   "stableUpdaterEnabled": False, "legacyUpgradeQualified": False,
                   "fullFeatureMigrationQualified": False, "dataProfile": "Native",
                   "candidate": True}
PREVIEW_FIELDS = {"releaseProfile": PREVIEW_PROFILE, "publicationForbidden": False,
                  "stableUpdaterEnabled": False, "legacyUpgradeQualified": False,
                  "fullFeatureMigrationQualified": False, "dataProfile": "NativePreview"}


def delivery(manifest):
    if not isinstance(manifest, dict):
        raise ValueError("invalid native delivery identity")
    if manifest.get("releaseProfile") == COMPLETE_PROFILE:
        if not re.fullmatch(r"5\.0\.0-rc\.[0-9]+", manifest.get("version", "")):
            raise ValueError("complete candidate identity requires 5.0.0-rc.N")
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
    if not re.fullmatch(r"5\.0\.0-rc\.[0-9]+", manifest.get("version", "")):
        raise ValueError("complete candidate version must be 5.0.0-rc.N")
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
    return {"publicationForbidden": True}
