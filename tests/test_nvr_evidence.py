"""Real synthetic MP4s plus durable job, failure, cancellation and reader contracts."""
import contextlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'nvr'))
import nvr_service as nvr
from evidence import EvidenceError, ExportJobs


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="WebOBS 证据 O'Brien ")
        root = pathlib.Path(self.temp.name)
        self.service = nvr.NvrService(root / 'config.json', root / 'storage')
        self.service.config['minFreeBytes'] = 0
        self.service.catalog.execute("INSERT INTO cameras VALUES('cam','Camera','off','main','copy',0)")
        # Direct library tests exercise the internal loopback identity. The full
        # product proxy test separately validates principal injection and RBAC.
        self.environment = mock.patch.dict(os.environ, {'WEBOBS_CLUSTER_INTERNAL_TOKEN': ''})
        self.environment.start()
        self.service.ffmpeg = shutil.which('ffmpeg') or str(ROOT / 'desktop/runtime/bin/ffmpeg.exe')
        self.service.ffprobe = shutil.which('ffprobe') or str(ROOT / 'desktop/runtime/bin/ffprobe.exe')
        self.request = {'cameraIds': ['cam'], 'fromUtcMs': 10000, 'toUtcMs': 12000, 'mode': 'exact', 'lock': True}

    def tearDown(self):
        self.service.jobs.drain()
        self.service.catalog.connection.close()
        self.environment.stop()
        self.temp.cleanup()

    def segment(self, start=10000, end=13000, name='a', audio=True):
        target = self.service.storage_root / f'{name}.mp4'
        command = [self.service.ffmpeg, '-v', 'error', '-nostdin', '-f', 'lavfi', '-i', 'color=c=blue:s=160x90:r=25']
        if audio:
            command += ['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000']
        command += ['-t', str((end-start)/1000), '-c:v', 'libx264', '-pix_fmt', 'yuv420p']
        if audio:
            command += ['-c:a', 'aac']
        subprocess.run(command + ['-y', str(target)], check=True, timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        identity = __import__('uuid').uuid4().hex
        self.service.catalog.add_segment({'id': identity, 'cameraId': 'cam', 'startUtcMs': start, 'endUtcMs': end,
            'durationMs': end-start, 'storageKey': target.name, 'kind': 'continuous', 'videoCodec': 'h264',
            'audioCodec': 'aac' if audio else '', 'sizeBytes': target.stat().st_size, 'integrity': 'ok'})
        return identity

    def submit(self, request=None):
        return self.service.jobs.submit('local-only', {**(request or self.request), 'requestId': 'a'*32})

    def terminal(self, job):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            result = self.service.jobs.get('local-only', job['id'])
            if result['state'] not in ExportJobs.ACTIVE:
                return result
            time.sleep(.05)
        self.fail('Job did not finish')

    def test_exact_audio_unicode_apostrophe_hash_and_atomic_completion(self):
        segment = self.segment()
        self.service.jobs.start()
        completed = self.terminal(self.submit())
        self.assertEqual(completed['state'], 'completed', completed)
        result = completed['result']
        self.assertTrue(any(track['type'] == 'audio' for track in result['files'][0]['tracks']))
        self.assertAlmostEqual(result['files'][0]['durationMs'], 2000, delta=80)
        target, _ = self.service.download_path(f"{result['exportId']}/cam.mp4")
        self.assertEqual(self.service._sha256(target), result['files'][0]['sha256'])
        subprocess.run([self.service.ffmpeg, '-v', 'error', '-i', str(target), '-f', 'null', '-'], check=True, timeout=20,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.assertTrue(self.service.segment_row(segment)['locked'])
        restored = ExportJobs(self.service)
        self.assertEqual(restored.get('local-only', completed['id'])['result'], result)

    def test_gap_exact_rejected_fast_manifest_reports_gap(self):
        self.segment(10000,11000,'a'); self.segment(12000,13000,'b')
        request = {**self.request, 'toUtcMs': 13000}
        with self.assertRaisesRegex(EvidenceError, 'continuous'):
            self.service.export_clip(request)
        result = self.service.export_clip({**request, 'mode': 'fast'})
        self.assertEqual(result['files'][0]['coverage']['gaps'], [{'fromUtcMs':11000,'toUtcMs':12000}])
        self.assertLess(result['files'][0]['durationMs'], 2500)

    def test_boundary_uses_half_open_range_and_silent_source_supported(self):
        first=self.segment(10000,11000,'a',False); second=self.segment(11000,12000,'b',False)
        result=self.service.export_clip({**self.request,'fromUtcMs':11000})
        self.assertEqual(result['sourceSegmentIds'],[second]); self.assertFalse(self.service.segment_row(first)['locked'])
        self.assertFalse(any(track['type']=='audio' for track in result['files'][0]['tracks']))

    def test_idempotency_queue_bound_conflict_and_owner_isolation(self):
        with mock.patch.object(self.service, 'authorize_export'):
            job=self.submit(); self.assertEqual(self.submit()['id'],job['id'])
            with self.assertRaises(EvidenceError):self.submit({**self.request,'toUtcMs':12500})
            with self.assertRaises(KeyError):self.service.jobs.get('another-user',job['id'])
            self.assertEqual(self.service.jobs.list('another-user'),{'jobs':[]})
            for index in range(7):
                self.service.jobs.submit('local-only',{**self.request,'requestId':f'{index:032x}'})
            with self.assertRaisesRegex(EvidenceError,'queue'):self.service.jobs.submit('local-only',{**self.request,'requestId':'b'*32})
            for item in self.service.jobs.list('local-only')['jobs']:self.service.jobs.cancel('local-only',item['id'])

    def test_restart_marks_unfinished_interrupted_and_removes_only_private_partial(self):
        job=self.submit(); target=self.service.exports_root/job['id']; target.mkdir();(target/'partial.mp4').write_bytes(b'partial')
        self.service.jobs=ExportJobs(self.service)
        self.assertEqual(self.service.jobs.get('local-only',job['id'])['state'],'interrupted');self.assertFalse(target.exists())

    def test_disk_failure_publishes_no_result_or_locks(self):
        segment=self.segment(); self.service.jobs.start()
        with mock.patch('evidence.shutil.disk_usage',return_value=type('Usage',(),{'free':0})()):
            job=self.terminal(self.submit())
        self.assertEqual(job['state'],'failed');self.assertEqual(job['error']['code'],'export_disk_full')
        self.assertFalse(self.service.segment_row(segment)['locked']);self.assertFalse((self.service.exports_root/job['id']).exists())

    def test_cancel_terminates_real_converter_and_releases_sources(self):
        segment=self.segment(); entered=threading.Event()
        original=__import__('evidence').run_export
        def slow(command,cancel):
            entered.set()
            # A real child waits instead of producing output; cancellation must stop it.
            return original([sys.executable,'-c','import time;time.sleep(120)'],cancel)
        self.service.jobs.start()
        with mock.patch('evidence.run_export',side_effect=slow):
            job=self.submit();self.assertTrue(entered.wait(5))
            with self.assertRaisesRegex(nvr.ConfigError,'active'):self.service.delete_segment(segment)
            self.service.jobs.cancel('local-only',job['id']); result=self.terminal(job)
        self.assertEqual(result['state'],'cancelled');self.assertFalse(self.service.active_readers)
        self.assertFalse(self.service.segment_row(segment)['locked']);self.assertFalse((self.service.exports_root/job['id']).exists())

    def test_unpublished_download_not_visible(self):
        job=self.submit();target=self.service.exports_root/job['id'];target.mkdir();(target/'cam.mp4').write_bytes(b'partial')
        with self.assertRaises(KeyError):self.service.download_path(f"{job['id']}/cam.mp4")
        self.service.jobs.cancel('local-only',job['id'])

    def test_publication_failure_rolls_back_source_locks_export_and_job_result(self):
        segment=self.segment(); self.service.jobs.start()
        with mock.patch.object(self.service.jobs,'complete',side_effect=RuntimeError('transaction failure')):
            job=self.terminal(self.submit())
        self.assertEqual(job['state'],'failed');self.assertFalse(self.service.segment_row(segment)['locked'])
        self.assertFalse(self.service.catalog.query('SELECT * FROM exports'))
        self.assertIsNone(job['result']);self.assertFalse((self.service.exports_root/job['id']).exists())

    def test_download_checks_owner_and_current_camera_scope(self):
        self.segment();self.service.jobs.start();job=self.terminal(self.submit())
        relative=f"{job['id']}/cam.mp4"
        with self.assertRaises(KeyError):self.service.download_path(relative,'other-user')
        with mock.patch.object(self.service,'authorize_export',side_effect=EvidenceError('export_scope_rejected','Revoked',403)):
            with self.assertRaises(EvidenceError):self.service.download_path(relative)

    def test_shutdown_refuses_queued_evidence_until_it_is_handled(self):
        job=self.submit()
        with self.assertRaisesRegex(RuntimeError,'jobs did not finish'):self.service.jobs.drain(timeout=.01)
        self.assertTrue(self.service.jobs.accepting)
        self.service.jobs.cancel('local-only',job['id'])

    def test_overlap_and_tampered_source_cannot_claim_exact_evidence(self):
        first=self.segment();second=self.segment(10500,11500,'overlap')
        with self.assertRaisesRegex(EvidenceError,'non-overlapping'):self.service.export_clip(self.request)
        self.service.catalog.execute("UPDATE segments SET integrity='deleted' WHERE id=?",(second,))
        self.service.catalog.execute('UPDATE segments SET sha256=? WHERE id=?',('f'*64,first))
        self.service.jobs.start();job=self.terminal(self.submit())
        self.assertEqual(job['error']['code'],'export_source_changed');self.assertFalse(self.service.segment_row(first)['locked'])

    def test_oversized_output_is_rejected_before_publishing_an_undownloadable_result(self):
        segment=self.segment();self.service.jobs.start()
        def oversized(command,_cancel):
            with pathlib.Path(command[-1]).open('wb') as output:output.truncate((64<<20)+1)
        with mock.patch('evidence.run_export',side_effect=oversized):job=self.terminal(self.submit())
        self.assertEqual(job['state'],'failed');self.assertEqual(job['error']['code'],'export_file_too_large')
        self.assertFalse(self.service.segment_row(segment)['locked']);self.assertFalse((self.service.exports_root/job['id']).exists())


if __name__ == '__main__':
    unittest.main()
