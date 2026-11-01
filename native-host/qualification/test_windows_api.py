#!/usr/bin/env python3
"""Optional real Windows API fixture; does not launch or stop any product."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest


@unittest.skipUnless(os.name == "nt", "Actual Windows x64 APIs are not available")
class WindowsApiTests(unittest.TestCase):
    def test_current_process_times_memory_and_snapshot(self):
        import win32
        current = win32.Process(os.getpid(), 0, "python-fixture", None)
        try:
            first = current.observe()
            self.assertFalse(first["exited"])
            self.assertGreater(first["createdFileTime"], 0)
            self.assertIsNotNone(first["cpuTime100ns"])
            self.assertGreater(first["workingSetBytes"], 0)
            self.assertGreater(first["privateBytes"], 0)
            self.assertTrue(Path(current.image()).is_absolute())
            self.assertIn(os.getpid(), [p["pid"] for p in win32.snapshot()])
            self.assertGreater(win32.logical_processors(), 0)
            self.assertGreater(win32.system_file_time(), first["createdFileTime"])
        finally:
            current.close()

    def test_retained_handle_final_cpu_and_private_directory(self):
        import win32
        # A separate synthetic Python fixture, never OBS/WebOBS or an existing user process.
        fixture = subprocess.Popen([sys.executable, "-c",
                                    "import sys,time; sys.stdin.buffer.read(1); end=time.perf_counter()+.2\nwhile time.perf_counter()<end: pass"],
                                   stdin=subprocess.PIPE)
        handle = None
        try:
            handle = win32.Process(fixture.pid, os.getpid(), "python-fixture", None)
            created = handle.created
            fixture.stdin.write(b"1"); fixture.stdin.close()
            fixture.wait(timeout=10)
            final = handle.observe()
            self.assertTrue(final["exited"])
            self.assertEqual(final["createdFileTime"], created)
            self.assertGreater(final["cpuTime100ns"], 0)
            self.assertGreaterEqual(final["exitFileTime"], created)
            self.assertIsNone(final["workingSetBytes"])
            self.assertIsNone(final["privateBytes"])
        finally:
            if fixture.poll() is None:
                # Only this newly-created disposable test fixture may be cleaned up.
                fixture.terminate(); fixture.wait(timeout=10)
            if handle: handle.close()
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "private-receipt"
            win32.create_private_directory(directory)
            (directory / "fixture.txt").write_text("synthetic fixture")
            self.assertEqual((directory / "fixture.txt").read_text(), "synthetic fixture")
            with self.assertRaises(OSError): win32.create_private_directory(directory)

    def test_private_directory_dacl_is_protected_and_only_user_and_system(self):
        import ctypes as C
        from ctypes import wintypes as W
        import win32

        class ACL_SIZE_INFORMATION(C.Structure):
            _fields_ = [("AceCount", W.DWORD), ("AclBytesInUse", W.DWORD),
                        ("AclBytesFree", W.DWORD)]

        class ACE_HEADER(C.Structure):
            _fields_ = [("AceType", W.BYTE), ("AceFlags", W.BYTE), ("AceSize", W.WORD)]

        class ACCESS_ALLOWED_ACE(C.Structure):
            _fields_ = [("Header", ACE_HEADER), ("Mask", W.DWORD), ("SidStart", W.DWORD)]

        get_security = win32.signature(win32.advapi, "GetNamedSecurityInfoW", W.DWORD,
                                       [W.LPWSTR, C.c_int, W.DWORD, C.c_void_p, C.c_void_p,
                                        C.POINTER(C.c_void_p), C.c_void_p, C.POINTER(C.c_void_p)])
        get_control = win32.signature(win32.advapi, "GetSecurityDescriptorControl", W.BOOL,
                                      [C.c_void_p, C.POINTER(W.WORD), C.POINTER(W.DWORD)])
        get_dacl = win32.signature(win32.advapi, "GetSecurityDescriptorDacl", W.BOOL,
                                   [C.c_void_p, C.POINTER(W.BOOL), C.POINTER(C.c_void_p),
                                    C.POINTER(W.BOOL)])
        get_acl_info = win32.signature(win32.advapi, "GetAclInformation", W.BOOL,
                                       [C.c_void_p, C.c_void_p, W.DWORD, C.c_int])
        get_ace = win32.signature(win32.advapi, "GetAce", W.BOOL,
                                  [C.c_void_p, W.DWORD, C.POINTER(C.c_void_p)])

        def sid_text(sid):
            text = W.LPWSTR()
            win32.checked(win32.ConvertSidToStringSidW(sid, C.byref(text)))
            try:
                return text.value
            finally:
                win32.LocalFree(C.cast(text, C.c_void_p))

        # Derive the actual token SID independently of the directory's ACL entries.
        token = W.HANDLE()
        win32.checked(win32.OpenProcessToken(win32.GetCurrentProcess(), 0x0008, C.byref(token)))
        try:
            length = W.DWORD()
            win32.GetTokenInformation(token, 1, None, 0, C.byref(length))
            self.assertGreater(length.value, 0)
            token_user = C.create_string_buffer(length.value)
            win32.checked(win32.GetTokenInformation(token, 1, token_user, length, C.byref(length)))
            user_sid = sid_text(C.cast(token_user, C.POINTER(C.c_void_p))[0])
        finally:
            win32.CloseHandle(token)

        with tempfile.TemporaryDirectory(prefix="webobs-private-acl-test-") as tmp:
            directory = Path(tmp) / "private-receipt"
            win32.create_private_directory(directory)
            descriptor = C.c_void_p(); dacl = C.c_void_p()
            error = get_security(str(directory), 1, 0x00000004, None, None,
                                 C.byref(dacl), None, C.byref(descriptor))
            if error:
                raise C.WinError(error)
            try:
                control = W.WORD(); revision = W.DWORD()
                win32.checked(get_control(descriptor, C.byref(control), C.byref(revision)))
                self.assertTrue(control.value & 0x1000, "SE_DACL_PROTECTED is required")
                present = W.BOOL(); defaulted = W.BOOL(); actual_dacl = C.c_void_p()
                win32.checked(get_dacl(descriptor, C.byref(present), C.byref(actual_dacl),
                                       C.byref(defaulted)))
                self.assertTrue(present.value)
                self.assertFalse(defaulted.value)
                self.assertIsNotNone(actual_dacl.value, "A NULL DACL grants public access")
                self.assertEqual(actual_dacl.value, dacl.value)
                size = ACL_SIZE_INFORMATION()
                win32.checked(get_acl_info(dacl, C.byref(size), C.sizeof(size), 2))
                self.assertEqual(size.AceCount, 2, "No additional public or inherited ACEs allowed")
                trustees = []
                for index in range(size.AceCount):
                    pointer = C.c_void_p()
                    win32.checked(get_ace(dacl, index, C.byref(pointer)))
                    ace = C.cast(pointer, C.POINTER(ACCESS_ALLOWED_ACE)).contents
                    self.assertGreaterEqual(ace.Header.AceSize, C.sizeof(ACCESS_ALLOWED_ACE))
                    self.assertEqual(ace.Header.AceType, 0, "Only ACCESS_ALLOWED_ACE is allowed")
                    self.assertEqual(ace.Header.AceFlags, 0x03,
                                     "Each ACE must inherit to files/directories, not be inherited itself")
                    self.assertEqual(ace.Mask, 0x001F01FF, "FILE_ALL_ACCESS is required")
                    trustees.append(sid_text(C.c_void_p(pointer.value + ACCESS_ALLOWED_ACE.SidStart.offset)))
                self.assertCountEqual(trustees, [user_sid, "S-1-5-18"])
                self.assertEqual(len(set(trustees)), 2)
            finally:
                win32.LocalFree(descriptor)

    def test_short_collection_keeps_its_already_started_fixture_alive(self):
        from collect import parser, run
        from common import summarize_samples
        import win32

        # This disposable test fixture is started and handshakes BEFORE run(). It stays
        # alive until this test closes its own stdin, not until the collector finishes.
        fixture_code = """import sys
print("fixture-ready", flush=True)
for command in sys.stdin:
    if command.strip() == "ping":
        print("fixture-alive", flush=True)
"""
        fixture = subprocess.Popen([sys.executable, "-u", "-c", fixture_code],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True)
        replies = queue.Queue()

        def read_replies():
            for line in fixture.stdout:
                replies.put(line.strip())

        reader = threading.Thread(target=read_replies, daemon=True)
        reader.start()
        try:
            self.assertEqual(replies.get(timeout=10), "fixture-ready")
            self.assertIsNone(fixture.poll())
            handle = win32.Process(fixture.pid, os.getpid(), "python-fixture", None)
            try:
                identity = handle.identity
                executable = Path(handle.image())
            finally:
                handle.close()
            with tempfile.TemporaryDirectory(prefix="webobs-private-collection-test-") as tmp:
                parent = Path(tmp).resolve()
                for ancestor in (parent, *parent.parents):
                    self.assertFalse((ancestor / ".git").exists(), "Fixture output must be outside Git")
                meta = json.loads((Path(__file__).parent / "metadata.example.json").read_text(encoding="utf-8"))
                meta.update({"campaignId": "synthetic-windows-test", "runId": "synthetic-run-01",
                             "pairId": "synthetic-pair-01", "workload": "fixture"})
                metadata_path = parent / "synthetic-metadata.json"
                with metadata_path.open("x", encoding="utf-8") as stream:
                    json.dump(meta, stream, allow_nan=False)
                output = parent / "private-collection"
                self.assertFalse(output.exists())
                args = parser().parse_args(["--pid", str(fixture.pid), "--exe", str(executable),
                                            "--metadata", str(metadata_path), "--output", str(output),
                                            "--fixture", "--warmup", "0", "--duration", "1",
                                            "--interval", ".25"])
                self.assertEqual(run(args), output)
                self.assertIsNone(fixture.poll(), "Collector must not terminate its observed root")
                fixture.stdin.write("ping\n"); fixture.stdin.flush()
                self.assertEqual(replies.get(timeout=10), "fixture-alive")
                self.assertEqual({p.name for p in output.iterdir()},
                                 {"metadata.json", "manifest.json", "samples.jsonl"})
                manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest["status"], "complete")
                self.assertTrue(manifest["fixture"])
                self.assertEqual(manifest["rootIdentity"], identity)
                self.assertEqual(manifest["rootExeSha256"], hashlib.sha256(executable.read_bytes()).hexdigest())
                for name, field in (("metadata.json", "metadataSha256"), ("samples.jsonl", "samplesSha256")):
                    self.assertEqual(manifest[field], hashlib.sha256((output / name).read_bytes()).hexdigest())
                self.assertEqual(json.loads((output / "metadata.json").read_text(encoding="utf-8")), meta)
                samples = [json.loads(line) for line in (output / "samples.jsonl").read_text(encoding="utf-8").splitlines()]
                self.assertGreaterEqual(len(samples), 2)
                self.assertEqual(samples[0]["phase"], "baseline")
                self.assertTrue(all(s["phase"] == "measure" for s in samples[1:]))
                for sample in samples:
                    root = next(p for p in sample["processes"] if p["identity"] == identity)
                    self.assertFalse(root["exited"])
                    self.assertIsInstance(root["cpuTime100ns"], int)
                    self.assertGreater(root["workingSetBytes"], 0)
                    self.assertGreater(root["privateBytes"], 0)
                summary = manifest["summary"]
                self.assertEqual(summary, summarize_samples(samples, manifest["logicalProcessors"]))
                self.assertGreaterEqual(summary["durationSeconds"], 1)
                self.assertGreaterEqual(summary["intervals"], 1)
                self.assertIsNotNone(summary["cpuNormalizedPercent"]["mean"])
                for receipt in (manifest, summary):
                    self.assertTrue(receipt["coverageIncomplete"])
                    self.assertFalse(receipt["strictTotal"])
                    self.assertFalse(receipt["qualified"])
                    self.assertTrue(all(value is None for value in receipt["unmeasured"].values()))
                self.assertEqual(manifest["timing"]["requestedWarmupSeconds"], 0)
                self.assertEqual(manifest["timing"]["requestedDurationSeconds"], 1)
                self.assertEqual(manifest["timing"]["intervalSeconds"], .25)
                self.assertIsNone(fixture.poll())
        finally:
            # Only our own newly-created fixture can be cleaned up, after collection.
            if fixture.stdin:
                fixture.stdin.close()
            try:
                fixture.wait(timeout=10)
            except subprocess.TimeoutExpired:
                fixture.terminate(); fixture.wait(timeout=10)
            reader.join(timeout=10)
            if fixture.stdout:
                fixture.stdout.close()


if __name__ == "__main__":
    unittest.main()
