"""Run the real Bash identity helper without building or publishing artifacts."""
from pathlib import Path
import os
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which('bash')
if os.name == 'nt' and shutil.which('git'):
    git_bash = Path(shutil.which('git')).resolve().parents[1] / 'bin' / 'bash.exe'
    BASH = str(git_bash) if git_bash.is_file() else None

@unittest.skipUnless(BASH, 'Requires Bash')
class ReleaseIdentityTest(unittest.TestCase):
    def identity(self, tag, milestone=''):
        environment = {**os.environ, 'WEBOBS_TARGET_MILESTONE': milestone, 'WEBOBS_TEST_RELEASE_TAG': tag}
        return subprocess.run([BASH, '-c', 'source "$1"; webobs_release_identity "$WEBOBS_TEST_RELEASE_TAG" || exit $?; printf "%s %s" "$build_version" "$build_milestone"',
                               '_', (ROOT / 'scripts/release-identity.sh').as_posix()],
                              capture_output=True, text=True, encoding='utf-8', env=environment, timeout=10)

    def test_patch_identity_and_reviewed_milestone_are_independent(self):
        for tag, expected in [('v4.0', '4.0.0'), ('v4.0.1', '4.0.1'), ('v4.0.2', '4.0.2'), ('v4.0.10', '4.0.10')]:
            with self.subTest(tag=tag):
                result = self.identity(tag, 'v4-M1')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, expected + ' v4-M1')
        result = self.identity('v3.5')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '3.5.0 v3-M2')

    def test_v4_does_not_silently_use_a_v2_or_unreviewed_gate(self):
        for milestone in ['', 'v3-M2', 'v4-M1-dev', 'v5-M1', 'v4-M0', 'v4-M01']:
            with self.subTest(milestone=milestone):
                self.assertNotEqual(self.identity('v4.0.1', milestone).returncode, 0)
        for tag in ['v04.0.1', 'v4.00.1', 'v4.0.01', 'v4.0.1-dev.1', 'v4.0.1\n']:
            with self.subTest(tag=tag):
                self.assertNotEqual(self.identity(tag, 'v4-M1').returncode, 0)

def dev_identity(milestone):
    return subprocess.run([BASH, '-c', 'source "$1"; webobs_dev_identity "$WEBOBS_TEST_DEV_MILESTONE" || exit $?; printf "%s" "$default_dev_version"',
                           '_', (ROOT / 'scripts/release-identity.sh').as_posix()],
                          capture_output=True, text=True, encoding='utf-8',
                          env={**os.environ, 'WEBOBS_TEST_DEV_MILESTONE': milestone}, timeout=10)

@unittest.skipUnless(BASH, 'Requires Bash')
class DevIdentityTest(unittest.TestCase):
    def test_current_line_defaults_to_the_v4_gate_and_keeps_history(self):
        for milestone, expected in [('v4-M1-dev', '4.0.0-dev'), ('v3-M2-dev', '3.1.0-dev'), ('v2-M7-dev', '2.3.0-dev')]:
            with self.subTest(milestone=milestone):
                result = dev_identity(milestone)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, expected)

    def test_unreviewed_development_milestones_fail_closed(self):
        for milestone in ['', 'v4-M1', 'v4-M2-dev', 'v5-M1-dev', 'v4-m1-dev', 'v4-M01-dev', 'v4-M1-dev ']:
            with self.subTest(milestone=milestone):
                self.assertNotEqual(dev_identity(milestone).returncode, 0)

@unittest.skipUnless(shutil.which('pwsh'), 'Requires PowerShell 7')
class TargetIdentityConsistencyTest(unittest.TestCase):
    """The three primary targets must accept one release version and reject the wrong class."""

    def pwsh(self, command, timeout=30):
        return subprocess.run(['pwsh', '-NoProfile', '-Command', command], capture_output=True,
                              text=True, encoding='utf-8', timeout=timeout)

    def test_android_accepts_the_same_stable_version_as_the_container(self):
        script = str(ROOT / 'android' / 'scripts' / 'release-version.ps1').replace("'", "''")
        result = self.pwsh(f"$ErrorActionPreference='Stop'; . '{script}'; "
                           "(Get-WebOBSAndroidReleaseIdentity -Version '4.0.0').VersionCode")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '4000000')
        # The same A.B.C string the container tag v4.0 resolves to.
        container = subprocess.run([BASH, '-c', 'source "$1"; WEBOBS_TARGET_MILESTONE=v4-M1 webobs_release_identity v4.0; printf "%s" "$build_version"',
                                    '_', (ROOT / 'scripts/release-identity.sh').as_posix()],
                                   capture_output=True, text=True, encoding='utf-8', timeout=10)
        self.assertEqual(container.stdout, '4.0.0')

    def test_windows_core_milestone_is_explicit_and_matches_the_release_class(self):
        script = str(ROOT / 'desktop/scripts/release-milestone.ps1').replace("'", "''")
        for version, release, milestone in [('4.0.0', '$true', 'v4-M1'), ('4.0.1', '$true', 'v4-M1'),
                                             ('4.0.0-dev.1', '$false', 'v4-M1-dev')]:
            with self.subTest(version=version):
                result = self.pwsh(f"$ErrorActionPreference='Stop'; . '{script}'; "
                                   f"Resolve-WebOBSDesktopMilestone -Version '{version}' -Release {release} -Milestone '{milestone}'")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), milestone)

    def test_windows_core_rejects_missing_mismatched_and_wrong_class_gates(self):
        script = str(ROOT / 'desktop/scripts/release-milestone.ps1').replace("'", "''")
        for version, release, milestone in [('4.0.0', '$true', ''), ('4.0.0', '$true', 'v3-M2'),
                                             ('4.0.0', '$true', 'v4-M1-dev'), ('4.0.0', '$true', 'v5-M1'),
                                             ('4.0.0', '$true', 'v4-M01'), ('4.0.0', '$true', 'v4-M1\n'),
                                             ('4.0.0-dev.1', '$false', 'v4-M1'), ('4.0.0', '$false', 'v4-M1-dev')]:
            with self.subTest(version=version, milestone=milestone):
                result = self.pwsh(f"$ErrorActionPreference='Stop'; . '{script}'; "
                                   f"Resolve-WebOBSDesktopMilestone -Version '{version}' -Release {release} -Milestone '{milestone}'")
                self.assertNotEqual(result.returncode, 0)

    @unittest.skipUnless(os.name == 'nt', 'Windows packaging validation runs on Windows')
    def test_windows_packaging_separates_release_and_development_classes(self):
        script = str(ROOT / 'desktop' / 'scripts' / 'build-windows.ps1')
        cases = [
            (['-Version', '4.0.0'], 'Development builds require a -dev.* version.'),
            (['-Version', '4.0.0-dev.1', '-Release'], 'Release builds require a stable X.Y.Z version.'),
            (['-Version', 'v4.0.0', '-Release'], 'Use a stable X.Y.Z or X.Y.Z-dev.* version.'),
        ]
        for arguments, expected in cases:
            with self.subTest(arguments=arguments):
                # Parameter names must stay unquoted; only values are quoted.
                quoted = ' '.join(value if value.startswith('-') else "'" + value + "'" for value in arguments)
                result = self.pwsh(f"& '{script}' {quoted}")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, (result.stdout or '') + (result.stderr or ''))

if __name__ == '__main__':
    unittest.main()
