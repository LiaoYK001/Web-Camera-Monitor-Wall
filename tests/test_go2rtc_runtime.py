import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
GO2RTC_ROOT = Path(os.environ.get('WEBOBS_TEST_GO2RTC_ROOT', str(ROOT / 'go2rtc')))
spec = importlib.util.spec_from_file_location('go2rtc_runtime', GO2RTC_ROOT / 'runtime.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class RuntimeTests(unittest.TestCase):
    def test_first_start_is_private_and_restart_preserves_user_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'go2rtc/go2rtc.yaml'
            runtime.prepare_config(config, GO2RTC_ROOT / 'go2rtc.yaml')
            self.assertIn('streams: {}', config.read_text())
            custom = 'streams:\n  test: rtsp://192.0.2.2/live\n'
            config.write_text(custom)
            runtime.prepare_config(config, GO2RTC_ROOT / 'go2rtc.yaml')
            self.assertEqual(config.read_text(), custom)
            if os.name == 'posix':
                self.assertEqual(config.stat().st_mode & 0o777, 0o600)
                self.assertEqual(config.parent.stat().st_mode & 0o777, 0o700)

    @unittest.skipUnless(os.name == 'posix', 'symlink contract runs in Linux')
    def test_symlink_config_is_rejected_without_overwriting_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'original'
            target.write_text('keep')
            config = root / 'go2rtc.yaml'
            config.symlink_to(target)
            with self.assertRaises(ValueError):
                runtime.prepare_config(config, GO2RTC_ROOT / 'go2rtc.yaml')
            self.assertEqual(target.read_text(), 'keep')

    def test_runtime_overlay_locks_management_boundary(self):
        overlay = json.loads(runtime.runtime_overlay(Path('/private/www')))
        self.assertEqual(overlay['api']['listen'], '127.0.0.1:11984')
        self.assertEqual(overlay['api']['base_path'], '/api/v1/go2rtc')
        self.assertEqual(overlay['api']['unix_listen'], '')
        self.assertEqual(overlay['api']['tls_listen'], '')
        self.assertEqual(overlay['api']['static_dir'], str(Path('/private/www')))
        self.assertEqual(overlay['rtsp']['listen'], '127.0.0.1:18554')
        self.assertEqual(overlay['webrtc']['listen'], '127.0.0.1:18555' if os.name == 'nt' else ':18555')
        self.assertNotIn('streams', overlay)


if __name__ == '__main__':
    unittest.main()
