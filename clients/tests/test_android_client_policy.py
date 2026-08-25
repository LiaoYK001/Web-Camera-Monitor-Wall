#!/usr/bin/env python3
"""Fail-closed source policy checks for the Android v2-M3 client boundary."""

from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "clients" / "android"
MANIFEST = ANDROID / "AndroidManifest.xml"
ACTIVITY = ANDROID / "src" / "org" / "webobs" / "nativeclient" / "WebObsActivity.java"
KEYSTORE = ANDROID / "src" / "org" / "webobs" / "nativeclient" / "KeyStoreBridge.java"
QML = ROOT / "clients" / "qml" / "Main.qml"
MEDIA_PIPELINE = ROOT / "clients" / "src" / "media_pipeline.cpp"
CLIENT_CONTROLLER = ROOT / "clients" / "src" / "client_controller.cpp"
MAIN = ROOT / "clients" / "src" / "main.cpp"
PROBE_ACTIVITY = (ANDROID / "src" / "org" / "webobs" / "nativeclient" /
                  "WebObsProbeActivity.java")
ANDROID_BUILD = ROOT / "clients" / "packaging" / "android" / "build.sh"
QML6_BUILD = ROOT / "clients" / "packaging" / "android" / "build-qml6-plugin.sh"
PATCH = (ROOT / "clients" / "packaging" / "android" / "patches" /
         "gst-plugins-good-1.28.6-qml6-android.patch")
ANDROID_NS = "{http://schemas.android.com/apk/res/android}"


class AndroidClientPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = ET.parse(MANIFEST).getroot()
        cls.activity = ACTIVITY.read_text(encoding="utf-8")
        cls.keystore = KEYSTORE.read_text(encoding="utf-8")
        cls.qml = QML.read_text(encoding="utf-8")
        cls.media_pipeline = MEDIA_PIPELINE.read_text(encoding="utf-8")
        cls.client_controller = CLIENT_CONTROLLER.read_text(encoding="utf-8")
        cls.main = MAIN.read_text(encoding="utf-8")
        cls.probe_activity = PROBE_ACTIVITY.read_text(encoding="utf-8")
        cls.android_build = ANDROID_BUILD.read_text(encoding="utf-8")
        cls.qml6_build = QML6_BUILD.read_text(encoding="utf-8")
        cls.patch = PATCH.read_text(encoding="utf-8")

    def test_android_10_arm64_runtime_boundary_is_bounded(self) -> None:
        uses_sdk = self.manifest.find("uses-sdk")
        self.assertIsNotNone(uses_sdk)
        self.assertEqual(uses_sdk.attrib[ANDROID_NS + "minSdkVersion"], "29")
        self.assertEqual(uses_sdk.attrib[ANDROID_NS + "targetSdkVersion"], "36")
        activity = self.manifest.find("application/activity")
        self.assertEqual(activity.attrib[ANDROID_NS + "name"],
                         "org.webobs.nativeclient.WebObsActivity")
        permissions = {item.attrib[ANDROID_NS + "name"]
                       for item in self.manifest.findall("uses-permission")}
        self.assertIn("android.permission.RECORD_AUDIO", permissions)
        self.assertNotIn("android.permission.READ_EXTERNAL_STORAGE", permissions)
        self.assertNotIn("android.permission.WRITE_EXTERNAL_STORAGE", permissions)
        self.assertNotIn("android.permission.MANAGE_EXTERNAL_STORAGE", permissions)
        probe = next(item for item in self.manifest.findall("application/activity")
                     if item.attrib[ANDROID_NS + "name"].endswith("WebObsProbeActivity"))
        self.assertEqual(probe.attrib[ANDROID_NS + "permission"],
                         "org.webobs.nativeclient.permission.RUN_ACCEPTANCE")
        self.assertEqual(probe.attrib[ANDROID_NS + "noHistory"], "false")
        self.assertEqual(probe.attrib[ANDROID_NS + "launchMode"], "singleTop")
        declared = self.manifest.find("permission")
        self.assertEqual(declared.attrib[ANDROID_NS + "protectionLevel"], "signature")

    def test_private_captures_cross_storage_boundary_only_through_saf(self) -> None:
        self.assertIn('new File(context.getFilesDir(), "captures")', self.activity)
        self.assertIn("Intent.ACTION_CREATE_DOCUMENT", self.activity)
        self.assertIn("getCanonicalFile()", self.activity)
        self.assertIn("MAX_EXPORT_BYTES", self.activity)
        self.assertNotIn("Environment.getExternalStorage", self.activity)
        self.assertNotIn("content://", self.activity)

    def test_manual_recording_is_exportable_only_after_muxer_flush(self) -> None:
        start = self.client_controller.index("bool ClientController::startManualRecording")
        stop = self.client_controller.index("void ClientController::stopManualRecording")
        listening = self.client_controller.index("void ClientController::setListening")
        start_body = self.client_controller[start:stop]
        stop_body = self.client_controller[stop:listening]
        self.assertIn("pending_recordings_.insert", start_body)
        self.assertNotIn("set_last_capture_path", start_body)
        self.assertIn("stopRecording(session_id)", stop_body)
        self.assertIn("pending_recordings_.take", stop_body)
        self.assertIn("set_last_capture_path", stop_body)

    def test_background_release_and_wake_lock_are_explicit(self) -> None:
        self.assertRegex(self.activity, re.compile(
            r"onPause\(\).*?setWakeLock\(false\)", re.DOTALL))
        self.assertIn("wakeLock.isHeld()", self.keystore)
        self.assertIn("wakeLockActive", self.qml)
        self.assertIn("EXTRA_RECONNECT", self.probe_activity)
        self.assertIn("EXTRA_FOREGROUND_RESUME", self.probe_activity)
        self.assertIn("EXTRA_MICROPHONE_PERMISSION", self.probe_activity)

    def test_android_keeps_the_qt_platform_and_media_has_a_stall_watchdog(self) -> None:
        platform_guard = self.main.index("#if !defined(Q_OS_ANDROID)")
        offscreen = self.main.index('qputenv("QT_QPA_PLATFORM", "offscreen")')
        platform_end = self.main.index("#endif", offscreen)
        self.assertLess(platform_guard, offscreen)
        self.assertLess(offscreen, platform_end)
        self.assertIn("last_video_frame_monotonic_ms_", self.media_pipeline)
        self.assertIn("camera_video_stalled_beyond_protocol_budget", self.media_pipeline)

    def test_sixteen_view_is_capability_and_thermal_gated(self) -> None:
        self.assertIn("getMaxSupportedInstances()", self.activity)
        self.assertIn("isHardwareAccelerated()", self.activity)
        self.assertIn("getCurrentThermalStatus()", self.activity)
        self.assertIn("clientController.grid16Available", self.qml)

    def test_gstreamer_qt6_delta_is_pinned_and_auditable(self) -> None:
        self.assertIn("exact, hash-verified", self.patch)
        self.assertIn("gst_gl_have_window_android", self.patch)
        self.assertIn("gst_gl_have_platform_egl", self.patch)
        self.assertIn("-DHAVE_QT_ANDROID", self.patch)
        self.assertNotIn("curl ", self.patch)
        self.assertIn("GST_PLUGIN_STATIC_REGISTER(qml6)", self.media_pipeline)
        self.assertIn("libgstqml6.a", self.qml6_build)
        self.assertNotIn("libgstqml6.so", self.android_build)


if __name__ == "__main__":
    unittest.main()
