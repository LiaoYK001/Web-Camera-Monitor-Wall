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

if __name__ == '__main__':
    unittest.main()
