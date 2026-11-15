"""Explicit, scoped delivery identity; it never qualifies complete migration."""
import re

PREVIEW_VERSION = "4.5.0"
PREVIEW_PROFILE = "native-monitor-preview"
PREVIEW_FIELDS = {"releaseProfile": PREVIEW_PROFILE, "publicationForbidden": False,
                  "stableUpdaterEnabled": False, "legacyUpgradeQualified": False,
                  "fullFeatureMigrationQualified": False, "dataProfile": "NativePreview"}


def delivery(manifest):
    if not isinstance(manifest, dict):
        raise ValueError("invalid native delivery identity")
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


def copy_delivery(manifest):
    return dict(PREVIEW_FIELDS) if delivery(manifest) == PREVIEW_PROFILE else {"publicationForbidden": True}
