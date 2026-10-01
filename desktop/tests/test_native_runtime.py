"""Snapshot and real Windows job lifecycle checks; never labels fixtures as media evidence."""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest
import sqlite3
from contextlib import closing

ROOT=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
def module(name, file):
    spec=importlib.util.spec_from_file_location(name,file);result=importlib.util.module_from_spec(spec);sys.modules[name]=result;spec.loader.exec_module(result);return result
snapshot=module('desktop_snapshot',ROOT/'desktop/python/snapshot.py')
transcoder=module('desktop_transcoder',ROOT/'desktop/python/transcoder.py')
private_directory=module('desktop_private_directory',ROOT/'desktop/python/private_directory.py')
headless=module('desktop_headless',ROOT/'desktop/scripts/prepare-obs-headless.py')

class SnapshotTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt' and (ROOT/'desktop/runtime/bin/ffmpeg.exe').exists(),'requires bundled Windows media tools')
    def test_windows_recording_stop_finalizes_a_playable_media_file(self):
        nvr=module('desktop_nvr_flush',ROOT/'nvr/nvr_service.py')
        runtime=ROOT/'desktop/runtime'
        with tempfile.TemporaryDirectory() as temp:
            output=pathlib.Path(temp)/'last-segment.mp4'
            process=subprocess.Popen([str(runtime/'bin/ffmpeg.exe'),'-hide_banner','-loglevel','error','-re','-f','lavfi','-i','testsrc2=size=160x90:rate=5','-c:v','mpeg4','-movflags','+frag_keyframe+empty_moov+default_base_moof',str(output)],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                deadline=time.monotonic()+10
                while not output.exists() and process.poll() is None and time.monotonic()<deadline:time.sleep(.05)
                self.assertTrue(output.exists());time.sleep(1)
                nvr.request_capture_stop(process);self.assertEqual(process.wait(timeout=10),0)
                probe=subprocess.run([str(runtime/'bin/ffprobe.exe'),'-v','error','-show_entries','format=duration:stream=codec_type','-of','json',str(output)],capture_output=True,text=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
                self.assertEqual(probe.returncode,0,probe.stderr);media=json.loads(probe.stdout)
                self.assertGreater(float(media['format']['duration']),0)
                self.assertTrue(any(stream['codec_type']=='video' for stream in media['streams']))
            finally:
                if process.stdin:process.stdin.close()
                if process.poll() is None:process.kill();process.wait()

    @unittest.skipUnless(os.name=='nt' and (ROOT/'desktop/runtime/python/python.exe').exists(),'requires a built Windows runtime')
    def test_bundled_inference_dependencies_import_without_developer_path(self):
        runtime=ROOT/'desktop/runtime';env={key:value for key,value in os.environ.items() if not key.upper().startswith(('PATH','PYTHON'))}
        env['PATH']=str(runtime/'bin')+os.pathsep+str(pathlib.Path(os.environ['SystemRoot'])/'System32')
        probe=subprocess.run([str(runtime/'python/python.exe'),'-B','-c','import sys,numpy,onnxruntime,flatbuffers,packaging,google.protobuf; assert sys.dont_write_bytecode; print(onnxruntime.__version__)'],capture_output=True,text=True,timeout=30,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(probe.returncode,0,probe.stderr)
        self.assertEqual(probe.stdout.strip(),'1.29.0')

    def test_headless_patch_matches_pinned_sources_and_never_changes_the_submodule(self):
        from unittest.mock import patch
        import shutil
        upstream=ROOT/'obs/obs-studio/plugins/obs-browser'
        before=(upstream/'browser-client.cpp').read_bytes()
        with self.assertRaises(ValueError):headless.prepare(upstream.parent.parent)
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp);source=root/'build/desktop-windows/obs-source';browser=source/'plugins/obs-browser';browser.mkdir(parents=True)
            for file in ('browser-client.cpp','obs-browser-source.cpp'):shutil.copyfile(upstream/file,browser/file)
            with patch.object(headless,'ROOT',root):headless.prepare(source);headless.prepare(source)
            self.assertNotIn('QCoreApplication::instance()->thread()', (browser/'browser-client.cpp').read_text())
        self.assertEqual((upstream/'browser-client.cpp').read_bytes(),before)

    @unittest.skipUnless(os.name=='nt','requires Windows DPAPI and ACL')
    def test_windows_keys_and_unicode_private_directory(self):
        from runtime_support import protect_local_key
        import ctypes
        from ctypes import wintypes
        key=os.urandom(32);encrypted=protect_local_key(key)
        self.assertNotEqual(encrypted,key);self.assertEqual(protect_local_key(encrypted,decrypt=True),key)
        with self.assertRaises(OSError):protect_local_key(encrypted[:-1],decrypt=True)
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp)/'场景 私密目录';root.mkdir();(root/'已有文件.txt').write_text('test')
            private_directory.protect(root)
            advapi=ctypes.WinDLL('advapi32',use_last_error=True)
            advapi.GetFileSecurityW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)]
            advapi.GetSecurityDescriptorControl.argtypes=[ctypes.c_void_p,ctypes.POINTER(wintypes.WORD),ctypes.POINTER(wintypes.DWORD)]
            for target in (root,root/'已有文件.txt'):
                needed=wintypes.DWORD();advapi.GetFileSecurityW(str(target),4,None,0,ctypes.byref(needed));buffer=ctypes.create_string_buffer(needed.value)
                self.assertTrue(advapi.GetFileSecurityW(str(target),4,buffer,needed,ctypes.byref(needed)))
                control=wintypes.WORD();revision=wintypes.DWORD();self.assertTrue(advapi.GetSecurityDescriptorControl(buffer,ctypes.byref(control),ctypes.byref(revision)))
                self.assertTrue(control.value & 0x1000,'DACL must not inherit broad access')

    def test_snapshot_is_verified_before_restoring_and_keeps_original_on_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp);data=root/'config';recordings=root/'recordings';data.mkdir();recordings.mkdir()
            (data/'scene.json').write_text('{"name":"场景"}',encoding='utf-8')
            # SQLite's transaction context does not close the database handle;
            # Windows forbids renaming the snapshot while those handles are open.
            for database in (data/'auth-sessions.db',recordings/'catalog.sqlite3'):
                with closing(sqlite3.connect(database)) as connection:
                    connection.execute('CREATE TABLE fixture (value TEXT)')
                    connection.execute("INSERT INTO fixture VALUES ('preserved')");connection.commit()
            target=root/'snapshot';snapshot.snapshot(data,recordings,target,'3.1.0')
            restored=root/'restored';snapshot.restore(target,restored,recordings)
            self.assertEqual((restored/'scene.json').read_text(encoding='utf-8'),'{"name":"场景"}')
            for database in (restored/'auth-sessions.db',recordings/'catalog.sqlite3'):
                with closing(sqlite3.connect(database)) as connection:
                    self.assertEqual(connection.execute('SELECT value FROM fixture').fetchone()[0],'preserved')
            (target/'config/scene.json').write_text('bad')
            with self.assertRaises(ValueError):snapshot.restore(target,root/'bad-restore',recordings)
            self.assertFalse((root/'bad-restore').exists());self.assertIn('场景',(data/'scene.json').read_text(encoding='utf-8'))

    def test_transcoder_uses_fixed_vectors_and_preserves_signed_audio_offsets(self):
        from unittest.mock import patch
        with patch.dict(os.environ,{'WEBOBS_FFMPEG_PATH':'D:/bundle/ffmpeg.exe','WEBOBS_MEDIAMTX_RTSP_PORT':'28554'}):
            args=transcoder.arguments(['direct-'+'a'*32,'mix-'+'b'*32,'audio-mix','0:1:0:-150,1:0.5:0:100'])
            self.assertIn('rtsp://127.0.0.1:28554/mix-'+'b'*32,args)
            graph=args[args.index('-filter_complex')+1];self.assertIn('delays=0',graph);self.assertIn('delays=250',graph)
            self.assertIn('setts=ts=TS+150/(1000*TB)',args)
            for values in [['rtsp://a b','mix-'+'b'*32,'audio-mix','0:1:0'],['direct-'+'a'*32,'hybrid-'+'b'*32,'transcode','; calc']]:
                with self.assertRaises(ValueError):transcoder.arguments(values)

    @unittest.skipUnless(os.name=='nt' and (ROOT/'desktop/runtime/bin/webobs-job.exe').exists(),'requires a built Windows runtime')
    def test_console_stop_reaches_owned_child_and_preserves_normal_exit(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp);ready=root/'ready';script=root/'console.py'
            script.write_text('import signal,time,pathlib,sys\nrunning=[True]\nsignal.signal(signal.SIGBREAK,lambda *_:running.__setitem__(0,False))\npathlib.Path(sys.argv[1]).write_text("ready")\nwhile running[0]:time.sleep(.05)\n')
            python=ROOT/'desktop/runtime/python/python.exe';job=ROOT/'desktop/runtime/bin/webobs-job.exe'
            child=subprocess.Popen([str(job),'--console',str(python),str(script),str(ready)],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                deadline=time.monotonic()+10
                while not ready.exists() and time.monotonic()<deadline:time.sleep(.05)
                self.assertTrue(ready.exists());child.stdin.write(b'shutdown\n');child.stdin.flush()
                self.assertEqual(child.wait(timeout=8),0)
            finally:
                if child.stdin:child.stdin.close()
                if child.poll() is None:child.kill();child.wait()

    @unittest.skipUnless(os.name=='nt' and (ROOT/'desktop/runtime/bin/webobs-job.exe').exists(),'requires a built Windows runtime')
    def test_job_kills_descendant_after_owner_disappears(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp);pidfile=root/'pid';script=root/'worker.py'
            script.write_text('import subprocess,sys,time,pathlib\np=subprocess.Popen([sys.executable,"-c","import time;time.sleep(300)"])\npathlib.Path(sys.argv[1]).write_text(str(p.pid))\ntime.sleep(300)\n')
            python=ROOT/'desktop/runtime/python/python.exe';job=ROOT/'desktop/runtime/bin/webobs-job.exe'
            child=subprocess.Popen([str(job),'--stdio',str(python),str(script),str(pidfile)],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                deadline=time.monotonic()+10
                while not pidfile.exists() and time.monotonic()<deadline:time.sleep(.05)
                self.assertTrue(pidfile.exists());pid=int(pidfile.read_text());child.kill();child.wait(timeout=10);time.sleep(.5)
                import ctypes
                kernel=ctypes.WinDLL('kernel32');kernel.OpenProcess.restype=ctypes.c_void_p
                handle=kernel.OpenProcess(0x1000,False,pid)
                if handle:
                    code=ctypes.c_ulong();kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)];kernel.GetExitCodeProcess(handle,ctypes.byref(code));kernel.CloseHandle.argtypes=[ctypes.c_void_p];kernel.CloseHandle(handle);self.assertNotEqual(code.value,259)
            finally:
                if child.stdin:child.stdin.close()
                if child.poll() is None:child.kill();child.wait()

if __name__=='__main__':unittest.main()
