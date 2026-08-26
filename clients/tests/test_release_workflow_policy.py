#!/usr/bin/env python3
"""Guard the trusted entry points of the native-client release workflow."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "release-native-clients.yaml"
IMAGE_WORKFLOW = ROOT / ".github" / "workflows" / "release-image.yaml"
WEB_WORKFLOW = ROOT / ".github" / "workflows" / "web-runtime-ci.yaml"


def branch(text: str, label: str) -> str:
    match = re.search(rf"^            {re.escape(label)}\)\n(?P<body>.*?)(?=^              ;;$)",
                      text, re.MULTILINE | re.DOTALL)
    if match is None:
        raise AssertionError(f"missing {label} identity branch")
    return match.group("body")


class NativeReleaseWorkflowPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.image_text = IMAGE_WORKFLOW.read_text(encoding="utf-8")
        cls.web_text = WEB_WORKFLOW.read_text(encoding="utf-8")

    def test_self_hosted_jobs_have_no_untrusted_event_entry(self) -> None:
        self.assertIn("  workflow_dispatch:\n", self.text)
        self.assertNotIn("  pull_request:\n", self.text)
        self.assertNotIn("  pull_request_target:\n", self.text)
        self.assertNotIn("  push:\n", self.text.split("permissions:", 1)[0])
        self.assertIn("BUILD-UNRELEASED-NATIVE-CANDIDATE", self.text)

    def test_manual_qualification_is_exact_protected_dev_tip(self) -> None:
        manual = branch(self.text, "workflow_dispatch")
        self.assertIn('[[ "$REF_TYPE" == branch && "$REF_NAME" == dev ]]', manual)
        self.assertIn('git fetch --no-tags origin dev', manual)
        self.assertIn('[[ "$(git rev-parse origin/dev)" == "$COMMIT_SHA" ]]', manual)
        self.assertIn('package_version="2.0.0-dev.sha.${COMMIT_SHA:0:12}"', manual)
        self.assertNotIn("publish_allowed=true", manual)
        self.assertNotIn("release_tag=", manual)

    def test_native_candidates_cannot_publish_v2_release_assets(self) -> None:
        self.assertNotIn("publish_allowed=true", self.text)
        self.assertNotIn("promote_latest=true", self.text)
        self.assertIn("    if: needs.audit.outputs.publish_allowed == 'true'", self.text)

    def test_older_queued_release_cannot_replace_latest_or_assets(self) -> None:
        self.assertIn("scripts/upload-release-assets-immutable.sh", self.image_text)
        self.assertIn("latest=(--latest=false)", self.image_text)
        self.assertNotIn("--clobber", self.image_text)

    def test_pwa_gates_use_only_trusted_self_hosted_entry_points(self) -> None:
        self.assertIn("runs-on: [self-hosted, linux, x64, webobs-builder]", self.web_text)
        self.assertIn("runs-on: [self-hosted, windows, x64, windows-11]", self.web_text)
        self.assertIn("if: github.event_name != 'pull_request'", self.web_text)
        self.assertIn("needs: [audit, pwa-fedora-gate, pwa-windows-gate]", self.image_text)
        self.assertIn("WEBOBS_FEDORA_PWA_GATE_COMMAND", self.image_text)
        self.assertIn("WEBOBS_WINDOWS_PWA_GATE_COMMAND", self.image_text)
        self.assertEqual(self.image_text.count("scripts/run-private-pwa-gate.py"), 2)
        self.assertGreaterEqual(self.web_text.count("pnpm test:local"), 2)
        self.assertGreaterEqual(self.image_text.count("pnpm test:local"), 2)
        self.assertIn('[[ "$REF_TYPE" == branch && ("$REF_NAME" == dev || "$REF_NAME" == main) ]]',
                      self.image_text)
        self.assertIn('[[ "$(git rev-parse "origin/$REF_NAME")" == "$GITHUB_SHA" ]]',
                      self.image_text)

    def test_candidate_windows_packages_cannot_skip_authenticode(self) -> None:
        self.assertIn("if ($env:CERTIFICATE_SHA1 -notmatch '^[0-9A-Fa-f]{40}$')", self.text)
        self.assertIn("-SigningCertificateSha1 $env:CERTIFICATE_SHA1", self.text)

    def test_desktop_release_requires_private_network_suspend_and_gpu_gate(self) -> None:
        self.assertEqual(self.text.count("run-desktop-lifecycle-gate.py"), 2)
        for variable in ("WEBOBS_DESKTOP_NETWORK_DISCONNECT_HELPER",
                         "WEBOBS_DESKTOP_NETWORK_CONNECT_HELPER",
                         "WEBOBS_DESKTOP_SUSPEND_HELPER"):
            self.assertGreaterEqual(self.text.count(variable), 4)
        for variable in ("WEBOBS_DESKTOP_GRANT_CAMERA_ID",
                         "WEBOBS_DESKTOP_GRANT_PROFILE_ID"):
            self.assertEqual(self.text.count(variable), 4)

    def test_built_desktop_artifacts_must_install_and_roll_back(self) -> None:
        self.assertIn("Qualify signed portable install and rollback", self.text)
        self.assertIn("Install-SignedPortableUpdate.ps1", self.text)
        self.assertIn("Signed portable rollback did not restore", self.text)
        self.assertIn("install-signed-appimage.sh", self.text)
        self.assertIn('cmp --silent "$destination" "$previous"', self.text)

    def test_android_release_is_signed_gated_and_never_uploads_private_driver(self) -> None:
        self.assertIn("  android:\n", self.text)
        self.assertIn("run-android-reference-gate.py", self.text)
        self.assertIn("build-acceptance-driver.sh", self.text)
        self.assertIn("WEBOBS_ANDROID_VPN_CONNECT_HELPER", self.text)
        self.assertIn("WEBOBS_ANDROID_VPN_DISCONNECT_HELPER", self.text)
        self.assertIn('--vpn-connect-helper "$WEBOBS_ANDROID_VPN_CONNECT_HELPER"', self.text)
        self.assertIn("WEBOBS_ANDROID_EXPIRY_CONTROL_URL", self.text)
        self.assertIn("WEBOBS_ANDROID_GRANT_CAMERA_ID", self.text)
        android_job = self.text[self.text.index("  android:\n"):self.text.index("  publish:\n")]
        self.assertIn("WEBOBS_ANDROID_EXPIRY_CONTROL_URL: ${{ vars.WEBOBS_ANDROID_EXPIRY_CONTROL_URL }}",
                      android_job)
        self.assertIn("WEBOBS_ANDROID_GRANT_CAMERA_ID: ${{ vars.WEBOBS_ANDROID_GRANT_CAMERA_ID }}",
                      android_job)
        self.assertIn("WEBOBS_ANDROID_GRANT_PROFILE_ID: ${{ vars.WEBOBS_ANDROID_GRANT_PROFILE_ID }}",
                      android_job)
        self.assertIn("needs: [audit, windows, linux, linux-acceptance, android]", self.text)
        upload = re.search(r"name: native-android-.*?if-no-files-found: error",
                           self.text, re.DOTALL)
        self.assertIsNotNone(upload)
        self.assertNotIn("private-driver", upload.group(0))

    def test_publish_requires_source_and_all_binary_sidecars(self) -> None:
        publish = self.text[self.text.index("  publish:\n"):]
        self.assertIn("scripts/create-source-bundle.sh", publish)
        self.assertIn("scripts/verify-source-bundle.sh", publish)
        self.assertIn('test "$count" -eq 5', publish)
        self.assertIn("*.spdx.json", publish)
        self.assertIn("*.sigstore.json", publish)


if __name__ == "__main__":
    unittest.main()
