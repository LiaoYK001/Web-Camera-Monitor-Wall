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
from unittest.mock import patch, Mock

ROOT=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
def module(name, file):
    spec=importlib.util.spec_from_file_location(name,file);result=importlib.util.module_from_spec(spec);sys.modules[name]=result;spec.loader.exec_module(result);return result
snapshot=module('desktop_snapshot',ROOT/'desktop/python/snapshot.py')
transcoder=module('desktop_transcoder',ROOT/'desktop/python/transcoder.py')
private_directory=module('desktop_private_directory',ROOT/'desktop/python/private_directory.py')
headless=module('desktop_headless',ROOT/'desktop/scripts/prepare-obs-headless.py')

class SnapshotTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt' and (ROOT/'desktop/runtime/bin/webobsd.exe').exists(),'requires a built Windows control runtime')
    def test_slow_account_operations_keep_login_and_failure_semantics(self):
        fixture=module('desktop_account_proxy',ROOT/'tests/account_proxy_runtime.py')
        fixture.exercise(ROOT/'desktop/runtime/bin/webobsd.exe',ROOT/'desktop/runtime/bin/webobs-job.exe')

    @unittest.skipUnless(os.name=='nt' and (ROOT/'desktop/runtime/bin/webobs-online-source.exe').exists(),'requires the complete website runtime')
    def test_online_sources_load_without_developer_path(self):
        runtime=ROOT/'desktop/runtime'
        env={key:value for key,value in os.environ.items() if not key.upper().startswith(('PATH','PYTHON','WEBOBS_'))}
        env.update(PATH=str(pathlib.Path(os.environ['SystemRoot'])/'System32'),PYTHONUTF8='1',
                   WEBOBS_NODE_PATH=str(runtime/'bin/node.exe'),WEBOBS_FFMPEG_PATH=str(runtime/'bin/ffmpeg.exe'))
        probe=subprocess.run([str(runtime/'bin/webobs-online-source.exe'),'--self-test'],capture_output=True,text=True,timeout=45,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(probe.returncode,0,probe.stderr)
        versions=json.loads(probe.stdout)
        locked=json.loads((ROOT/'go2rtc/online-source-dependencies.lock.json').read_text())['engines']
        for name in ('yt-dlp','streamlink'):self.assertEqual(versions[name],locked[name])
        self.assertEqual(versions['node'],'v'+locked['node'])

    @unittest.skipUnless(os.name=='nt' and (ROOT/'desktop/runtime/bin/webobs-online-source.exe').exists(),'requires the complete website runtime')
    def test_website_extractors_publish_and_stop_real_synthetic_rtsp(self):
        fixture=module('desktop_online_media',ROOT/'tests/online_source_media.py')
        fixture.exercise(ROOT/'desktop/runtime',drop_media=True)

    @unittest.skipUnless(os.name=='nt' and (ROOT/'desktop/runtime/bin/webobs-online-source.exe').exists(),'requires the complete website runtime')
    def test_website_media_rejects_untrusted_tls_before_http(self):
        fixture=module('desktop_online_tls',ROOT/'tests/online_source_tls.py')
        fixture.exercise(ROOT/'desktop/runtime')

    def test_signing_key_file_preserves_binary_ciphertext_on_restart(self):
        from unittest.mock import patch, Mock
        service=module('desktop_signing_persistence',ROOT/'v2/client_control_service.py')
        public,secret=b'p'*32,b's'*64
        protected=b'WEBOBSDPAPI1\nprotected\x00\xff\r\n'
        def protect(value,decrypt=False):
            self.assertEqual(value,protected if decrypt else public+secret)
            return public+secret if decrypt else protected
        with tempfile.TemporaryDirectory() as temp:
            key=pathlib.Path(temp)/'grant.key'
            with patch.object(service,'KEY_PATH',key),patch.object(service,'sodium',return_value=Mock(signing_keypair=Mock(return_value=(public,secret)))),patch.object(service,'protect_local_key',side_effect=protect):
                self.assertEqual(service.load_or_create_signing_key(),(public,secret))
                self.assertEqual(key.read_bytes(),protected)
                self.assertEqual(service.load_or_create_signing_key(),(public,secret))

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
    def test_owned_modify_only_profile_can_be_secured_without_write_owner(self):
        import ctypes
        from ctypes import wintypes
        advapi=ctypes.WinDLL('advapi32',use_last_error=True)
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.LocalFree.argtypes=[ctypes.c_void_p]
        advapi.GetFileSecurityW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)]
        advapi.GetSecurityDescriptorOwner.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(wintypes.BOOL)]
        advapi.ConvertSidToStringSidW.argtypes=[ctypes.c_void_p,ctypes.POINTER(wintypes.LPWSTR)]
        advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,ctypes.POINTER(ctypes.c_void_p),ctypes.c_void_p]
        advapi.SetFileSecurityW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,ctypes.c_void_p]
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp)/'owned-modify-profile';root.mkdir()
            private_directory.protect(root)
            needed=wintypes.DWORD();advapi.GetFileSecurityW(str(root),1,None,0,ctypes.byref(needed))
            buffer=ctypes.create_string_buffer(needed.value)
            self.assertTrue(advapi.GetFileSecurityW(str(root),1,buffer,needed,ctypes.byref(needed)))
            owner=ctypes.c_void_p();defaulted=wintypes.BOOL();owner_text=wintypes.LPWSTR()
            self.assertTrue(advapi.GetSecurityDescriptorOwner(buffer,ctypes.byref(owner),ctypes.byref(defaulted)))
            self.assertTrue(advapi.ConvertSidToStringSidW(owner,ctypes.byref(owner_text)))
            descriptor=ctypes.c_void_p()
            try:
                # Modify omits WRITE_OWNER and WRITE_DAC; the current owner has
                # implicit WRITE_DAC and can secure this directory without elevation.
                sddl=f'D:P(A;OICI;0x1301bf;;;{owner_text.value})'
                self.assertTrue(advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl,1,ctypes.byref(descriptor),None))
                self.assertTrue(advapi.SetFileSecurityW(str(root),0x80000004,descriptor))
                private_directory.protect(root)
                (root/'new-private-file').write_text('can write after securing')
                private_directory.protect(root)
            finally:
                if descriptor:kernel.LocalFree(descriptor)
                kernel.LocalFree(ctypes.cast(owner_text,ctypes.c_void_p))

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

    def test_hybrid_decode_fallback_preserves_hardware_encoding_and_passthrough(self):
        values=['direct-'+'a'*32,'hybrid-'+'b'*32,'transcode','copy']
        env={'WEBOBS_FFMPEG_PATH':'ffmpeg','WEBOBS_NVIDIA_ENCODE_SUPPORTED':'true','WEBOBS_NVIDIA_DECODE_SUPPORTED':'true','WEBOBS_HYBRID_VIDEO_ENCODER':'auto','WEBOBS_SOFTWARE_FALLBACK':'false'}
        with patch.dict(os.environ,env):
            call=Mock(side_effect=[1,0])
            self.assertEqual(transcoder.run_transcoder(values,call),0)
            first,second=[item.args[0] for item in call.call_args_list]
            self.assertLess(first.index('-hwaccel'),first.index('-i'))
            self.assertEqual(first[first.index('-hwaccel')+1],'cuda')
            self.assertNotIn('-hwaccel',second)
            self.assertEqual(second[second.index('-c:v')+1],'h264_nvenc')
            values[2]='copy'
            call=Mock(return_value=0);transcoder.run_transcoder(values,call)
            self.assertNotIn('-hwaccel',call.call_args.args[0])
            self.assertEqual(call.call_args.args[0][call.call_args.args[0].index('-c:v')+1],'copy')

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
