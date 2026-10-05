"""Exercise the actual PowerShell release identity used by Android packaging."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'release-version.ps1'

@unittest.skipUnless(shutil.which('pwsh'), 'Requires PowerShell 7')
class ReleaseIdentityTest(unittest.TestCase):
    def identities(self, versions):
        # Test-controlled fixed values; no credentials or publication commands.
        source = str(SCRIPT).replace("'", "''")
        values = ','.join("'" + version.replace("'", "''") + "'" for version in versions)
        command = f"$ErrorActionPreference='Stop'; . '{source}'; @({values}) | ForEach-Object {{ Get-WebOBSAndroidReleaseIdentity -Version $_ }} | ConvertTo-Json -Compress"
        return subprocess.run(['pwsh', '-NoProfile', '-Command', command], capture_output=True, text=True, encoding='utf-8', timeout=20)

    def test_patch_minor_major_codes_are_monotonic(self):
        result = self.identities(['4.0.0', '4.0.1', '4.0.2', '4.0.9', '4.0.10', '4.0.999', '4.1.0', '4.999.999', '5.0.0'])
        self.assertEqual(result.returncode, 0, result.stderr)
        identities = json.loads(result.stdout)
        codes = [identity['VersionCode'] for identity in identities]
        self.assertEqual(codes[:3], [4000000, 4000001, 4000002])
        self.assertTrue(all(before < after for before, after in zip(codes, codes[1:])))
        self.assertGreater(codes[0], 3050001)  # Existing development APK baseline.

    def test_invalid_and_overflow_versions_are_rejected(self):
        for version in ['3.5.1', '4.0', 'v4.0.1', '4.0.1-dev.1', '04.0.1', '4.0.01', '4.1000.0', '4.0.1000', '2100.0.1', '999999999.0.0', '4.0.1\n']:
            with self.subTest(version=version):
                self.assertNotEqual(self.identities([version]).returncode, 0)

if __name__ == '__main__':
    unittest.main()
