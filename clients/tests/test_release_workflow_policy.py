#!/usr/bin/env python3
"""Guard the trusted entry points of the native-client release workflow."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "release-native-clients.yaml"


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

    def test_self_hosted_jobs_have_no_untrusted_event_entry(self) -> None:
        self.assertIn("  workflow_dispatch:\n", self.text)
        self.assertNotIn("  pull_request:\n", self.text)
        self.assertNotIn("  pull_request_target:\n", self.text)

    def test_manual_qualification_is_exact_protected_dev_tip(self) -> None:
        manual = branch(self.text, "workflow_dispatch")
        self.assertIn('[[ "$REF_TYPE" == branch && "$REF_NAME" == dev ]]', manual)
        self.assertIn('git fetch --no-tags origin dev', manual)
        self.assertIn('[[ "$(git rev-parse origin/dev)" == "$COMMIT_SHA" ]]', manual)
        self.assertIn('package_version="2.0.0-dev.sha.${COMMIT_SHA:0:12}"', manual)
        self.assertNotIn("publish_allowed=true", manual)
        self.assertNotIn("release_tag=", manual)

    def test_only_main_reachable_semver_tag_can_publish(self) -> None:
        tagged = branch(self.text, "push")
        self.assertIn('[[ "$REF_TYPE" == tag ]]', tagged)
        self.assertIn('[[ "$REF_NAME" =~ ^v2\\.[0-9]+(\\.[0-9]+)?$ ]]', tagged)
        self.assertIn('git merge-base --is-ancestor "$COMMIT_SHA" origin/main', tagged)
        self.assertIn("publish_allowed=true", tagged)
        self.assertIn("    if: needs.audit.outputs.publish_allowed == 'true'", self.text)

    def test_candidate_windows_packages_cannot_skip_authenticode(self) -> None:
        self.assertIn("if ($env:CERTIFICATE_SHA1 -notmatch '^[0-9A-Fa-f]{40}$')", self.text)
        self.assertIn("-SigningCertificateSha1 $env:CERTIFICATE_SHA1", self.text)


if __name__ == "__main__":
    unittest.main()
