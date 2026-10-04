"""Website relay boundaries, compatible passthrough and verified archive installation."""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value
source = module('online_source', ROOT/'go2rtc/online_source.py')
installer = module('online_installer', ROOT/'scripts/install-online-source-runtime.py')
encode = lambda text: base64.urlsafe_b64encode(text.encode()).decode().rstrip('=')


class OnlineSourceTests(unittest.TestCase):
    def test_encoded_page_keeps_fragment_unicode_and_option_like_query_as_data(self):
        page='https://example.test/视频?x=--output#chapter'
        self.assertEqual(source.page_url(encode(page)),page)
        for value in ('https://user:secret@example.test/video','file:///private/cookies','https://example.test/\n--output','https://example.test:'+ 'a','https://example.test/'+'x'*2048):
            with self.subTest(value=value[:24]),self.assertRaises(source.SourceError):source.page_url(encode(value))
        for value in ('%%%','a','a'*3000):
            with self.assertRaises(source.SourceError):source.page_url(value)

    def test_output_only_accepts_go2rtc_current_loopback_port_and_digest(self):
        with patch.dict(os.environ,{'WEBOBS_GO2RTC_RTSP_PORT':'18557'}):
            self.assertEqual(source.output_url('rtsp://127.0.0.1:18557/'+'a'*32),'rtsp://127.0.0.1:18557/'+'a'*32)
            for value in ('rtsp://127.0.0.1:18554/'+'a'*32,'rtsp://localhost:18557/'+'a'*32,'rtsp://10.0.0.1:18557/'+'a'*32,'rtsp://127.0.0.1:18557/../../x'):
                with self.assertRaises(source.SourceError):source.output_url(value)

    def test_cookie_profile_is_private_and_cannot_select_arbitrary_files(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'WEBOBS_GO2RTC_CONFIG':str(Path(temp)/'go2rtc.yaml')}):
            cookies=Path(temp)/'cookies';cookies.mkdir();file=cookies/'account.txt';file.write_text('# Netscape HTTP Cookie File\n');file.chmod(0o600)
            self.assertEqual(source.cookie_file('account'),str(file))
            for value in ('../account','account.txt','other','/tmp/account'):
                with self.assertRaises(source.SourceError):source.cookie_file(value)
            file.write_bytes(b'x'*(1024*1024+1))
            with self.assertRaises(source.SourceError):source.cookie_file('account')

    def test_headers_reject_injection_and_bound_sensitive_values(self):
        self.assertEqual(source.safe_headers({'Cookie':'provider=private','User-Agent':'test','X-Product-Session':'never'}),'Cookie: provider=private\r\nUser-Agent: test\r\n')
        for headers in ({'Cookie':'x\r\nInjected: y'},{'Cookie':'x'*16385},{'Bad:Name':'x'}):
            with self.assertRaises(source.SourceError):source.safe_headers(headers)

    def test_https_proxy_and_no_proxy_are_selected_per_input_without_local_escape(self):
        with patch.object(source,'getproxies',return_value={'https':'http://proxy.example.test:3128','http':'http://other.example.test:3128'}),patch.object(source,'proxy_bypass',return_value=False):
            self.assertEqual(source.input_proxy('https://media.example.test/v.mp4'),'http://proxy.example.test:3128')
            self.assertEqual(source.input_proxy('http://media.example.test/v.mp4'),'http://other.example.test:3128')
            for local in ('http://127.0.0.1:19090/video','http://[::1]/video','http://localhost/video'):
                self.assertEqual(source.input_proxy(local),'')
            with patch.object(source,'proxy_bypass',return_value=True):self.assertEqual(source.input_proxy('https://bypass.example.test/video'),'')

    def test_unsupported_proxy_never_leaks_its_credentials_in_the_error(self):
        with patch.object(source,'getproxies',return_value={'https':'socks5://fixture:private@proxy.example.test:1080'}),patch.object(source,'proxy_bypass',return_value=False):
            with self.assertRaises(source.SourceError) as error:source.input_proxy('https://media.example.test/video')
            self.assertIn('proxy_unsupported',str(error.exception));self.assertNotIn('private',str(error.exception))

    def test_avc_aac_adaptive_tracks_copy_and_unknown_video_converts_only_on_demand(self):
        inputs=[dict(url='https://example.test/v.mp4',headers={},video='avc1.64001f',audio='none'),dict(url='https://example.test/a.m4a',headers={},video='none',audio='mp4a.40.2')]
        with patch.object(source,'binary',return_value='/fixed/ffmpeg'),patch.object(source,'input_proxy',return_value=''),patch.dict(os.environ,{'WEBOBS_GO2RTC_RTSP_PORT':'18554'}):
            command=source.ffmpeg_command(inputs,'rtsp://127.0.0.1:18554/'+'a'*32,'auto',720)
            self.assertEqual(command[command.index('-c:v')+1],'copy');self.assertEqual(command[command.index('-c:a')+1],'copy')
            self.assertIn('1:a:0?',command);self.assertNotIn('-vf',command)
            inputs[0]['video']='vp9';command=source.ffmpeg_command(inputs,'rtsp://127.0.0.1:18554/'+'a'*32,'auto',720)
            self.assertEqual(command[command.index('-c:v')+1],'libx264');self.assertNotIn('file',command[command.index('-protocol_whitelist')+1])

    def test_checksum_failure_never_replaces_cached_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cache=root/'cache';cache.mkdir();(cache/'tool.zip').write_bytes(b'old')
            wrong=root/'wrong.zip';wrong.write_bytes(b'wrong')
            with self.assertRaisesRegex(ValueError,'checksum'):
                installer.verified_download({'filename':'tool.zip','url':wrong.as_uri(),'sha256':hashlib.sha256(b'expected').hexdigest()},cache)
            self.assertEqual((cache/'tool.zip').read_bytes(),b'old');self.assertEqual(len(list(cache.iterdir())),1)

    def test_wheel_traversal_and_symbolic_links_do_not_escape_site(self):
        for name,mode in (('../outside.py',0),('bad.py',0o120777<<16)):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);archive=root/'bad.whl'
                with zipfile.ZipFile(archive,'w') as out:
                    member=zipfile.ZipInfo(name);member.external_attr=mode;out.writestr(member,'bad')
                lock=root/'lock.json';lock.write_text(json.dumps({'schemaVersion':1,'platforms':{'windows-x64':{'wheels':[{'name':'bad','filename':'bad.whl','url':archive.as_uri(),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}]}}}))
                with self.assertRaises(ValueError):installer.install(lock,'windows-x64',root/'cache',root/'site',root/'bin',root/'licenses')
                self.assertFalse((root/'outside.py').exists())


if __name__=='__main__':unittest.main()
