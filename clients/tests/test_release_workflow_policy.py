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

    def test_github_release_preflight_cannot_publish_packages(self) -> None:
        self.assertIn("name: Release preflight audit", self.image_text)
        self.assertNotIn("packages: write", self.image_text)
        self.assertNotIn("docker/login-action", self.image_text)
        self.assertNotIn("docker/build-push-action", self.image_text)
        self.assertNotIn("gh release create", self.image_text)
        self.assertIn("scripts/release-image-local.sh", self.image_text)

    def test_pwa_platform_gates_are_local_not_self_hosted(self) -> None:
        self.assertNotIn("runs-on: [self-hosted", self.web_text)
        self.assertNotIn("runs-on: [self-hosted", self.image_text)
        self.assertNotIn("WEBOBS_FEDORA_PWA_GATE_COMMAND", self.image_text)
        self.assertNotIn("WEBOBS_WINDOWS_PWA_GATE_COMMAND", self.image_text)
        self.assertIn("local WSL2 Linux and Windows hosts", self.web_text)
        release_script = (ROOT / "scripts" / "release-image-local.sh").read_text(encoding="utf-8")
        windows_release_script = (ROOT / "scripts" / "release-image-local.ps1").read_text(encoding="utf-8")
        gate_script = (ROOT / "scripts" / "run-private-pwa-gate.py").read_text(encoding="utf-8")
        self.assertIn("verify-local-gate-receipts.py", release_script)
        self.assertIn("release-image-local.sh", windows_release_script)
        self.assertIn('"linux-wsl2-chromium"', gate_script)
        self.assertIn('"windows"', gate_script)
        self.assertIn('[[ "$REF_TYPE" == branch && ("$REF_NAME" == dev || "$REF_NAME" == main) ]]',
                      self.image_text)
        self.assertIn('[[ "$remote_sha" == "$GITHUB_SHA" ]]', self.image_text)

    def test_local_image_release_uses_v23_scale_metadata_and_normalizes_semver(self) -> None:
        release_script = (ROOT / "scripts" / "release-image-local.sh").read_text(encoding="utf-8")
        windows_release_script = (ROOT / "scripts" / "release-image-local.ps1").read_text(encoding="utf-8")
        for marker in ("2.3.0-dev", "v2-M7-dev", "v2-M7", "v2-M6", "v2-M5"):
            self.assertIn(marker, release_script)
        self.assertIn("build_version", release_script)
        self.assertIn('build_version="${build_version}.0"', release_script)
        self.assertIn("release-image-local.sh", windows_release_script)

    def test_stable_image_release_promotes_only_the_verified_candidate_digest(self) -> None:
        release_script = (ROOT / "scripts" / "release-image-local.sh").read_text(encoding="utf-8")
        build = release_script.split("docker buildx build", 1)[1].split("if [ \"$version\" = dev ]", 1)[0]
        self.assertIn('sha-${short_revision}', build)
        self.assertNotIn('${image}:${version}', build)
        self.assertNotIn('${image}:latest', build)
        self.assertIn('gh release create "$version"', release_script)
        self.assertIn('gh release edit "$version"', release_script)
        self.assertIn('"${image}@${digest}"', release_script)

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
