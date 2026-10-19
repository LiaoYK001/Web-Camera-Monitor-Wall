#!/usr/bin/env python3
"""Protect qualification trust boundaries and diagnostic redaction."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('public_source_network', ROOT / 'desktop/tests/public-source-network.py')
network = importlib.util.module_from_spec(spec)
spec.loader.exec_module(network)


class PublicSourceQualificationTests(unittest.TestCase):
    def test_http_error_still_proves_verified_tls(self):
        error = urllib.error.HTTPError('https://private.example/?token=secret', 404, 'private', {}, None)
        with patch.object(network.urllib.request, 'urlopen', side_effect=error):
            result = network.tls_probe('manifest.googlevideo.com', object())
        self.assertEqual(result['tls'], 'verified')
        self.assertEqual(result['status'], 404)
        self.assertNotIn('secret', json.dumps(result))

    def test_transport_failure_retains_category_without_raw_url_or_credentials(self):
        error = urllib.error.URLError('EOF https://user:secret@private.example/?signed=secret')
        with patch.object(network.urllib.request, 'urlopen', side_effect=error):
            result = network.tls_probe('manifest.googlevideo.com', object())
        self.assertTrue(result['eof'])
        self.assertTrue(result['certificateVerification'])
        self.assertNotIn('tls', result)
        self.assertNotIn('secret', json.dumps(result))
        self.assertNotIn('private.example', json.dumps(result))

    def test_only_fixed_public_sources_can_be_selected(self):
        self.assertEqual(set(network.SOURCES), {'reported', 'dw', 'aljazeera'})
        self.assertTrue(all(url.startswith('https://www.youtube.com/') for url in network.SOURCES.values()))

    def test_reusable_workflow_cannot_execute_fork_or_failed_candidate(self):
        text = (ROOT / '.github/workflows/website-source-qualification.yaml').read_text()
        self.assertIn('  workflow_call:', text)
        for entry in ('  pull_request:', '  pull_request_target:', '  push:', '  workflow_dispatch:'):
            self.assertNotIn(entry, text)
        for guard in ("$run.conclusion -ne 'success'", "$run.event -ne 'workflow_dispatch'",
                      "$run.head_branch -ne 'dev'", "$run.head_repository.full_name -ne $env:GH_REPO",
                      'git merge-base --is-ancestor', 'Require exact remote dev tip',
                      "Missing immutable artifact identity", 'ref: ${{ steps.candidate.outputs.revision }}'):
            self.assertIn(guard, text)
        self.assertNotIn('contents: write', text)
        self.assertNotIn('packages: write', text)
        self.assertIn('digest-mismatch: error', text)
        upload = text.split('Retain only redacted receipts;', 1)[1]
        self.assertIn('/public-source-receipts/*.json', upload)
        self.assertNotIn('path: desktop', upload)


if __name__ == '__main__':
    unittest.main()
