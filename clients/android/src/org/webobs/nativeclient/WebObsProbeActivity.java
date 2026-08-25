package org.webobs.nativeclient;

import android.os.Bundle;
import android.content.Intent;
import android.util.Log;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;

/** Signature-protected entry point used only by the private Android reference gate. */
public final class WebObsProbeActivity extends WebObsActivity {
    public static final String EXTRA_MANIFEST = "org.webobs.nativeclient.extra.PROBE_MANIFEST";
    public static final String EXTRA_BACKGROUND_RELEASE =
            "org.webobs.nativeclient.extra.PROBE_BACKGROUND_RELEASE";
    public static final String EXTRA_RECONNECT =
            "org.webobs.nativeclient.extra.PROBE_RECONNECT";
    public static final String EXTRA_FOREGROUND_RESUME =
            "org.webobs.nativeclient.extra.PROBE_FOREGROUND_RESUME";
    public static final String EXTRA_MICROPHONE_PERMISSION =
            "org.webobs.nativeclient.extra.PROBE_MICROPHONE_PERMISSION";
    public static final String EXTRA_NETWORK_STATUS =
            "org.webobs.nativeclient.extra.PROBE_NETWORK_STATUS";
    public static final String EXTRA_CLIENT_AUTH =
            "org.webobs.nativeclient.extra.PROBE_CLIENT_AUTH";
    public static final String EXTRA_AUTH_OFFLINE =
            "org.webobs.nativeclient.extra.PROBE_AUTH_OFFLINE";
    public static final String EXTRA_CONTROL_URL =
            "org.webobs.nativeclient.extra.PROBE_CONTROL_URL";
    public static final String EXTRA_CAMERA_ID =
            "org.webobs.nativeclient.extra.PROBE_CAMERA_ID";
    public static final String EXTRA_PROFILE_ID =
            "org.webobs.nativeclient.extra.PROBE_PROFILE_ID";
    private static final int MAX_MANIFEST_BYTES = 1024 * 1024;
    private File privateManifest;

    @Override
    public void onCreate(Bundle state) {
        boolean backgroundRelease = getIntent() != null &&
                getIntent().getBooleanExtra(EXTRA_BACKGROUND_RELEASE, false);
        boolean reconnect = getIntent() != null &&
                getIntent().getBooleanExtra(EXTRA_RECONNECT, false);
        boolean foregroundResume = getIntent() != null &&
                getIntent().getBooleanExtra(EXTRA_FOREGROUND_RESUME, false);
        boolean microphonePermission = getIntent() != null &&
                getIntent().getBooleanExtra(EXTRA_MICROPHONE_PERMISSION, false);
        boolean clientAuth = getIntent() != null &&
                getIntent().getBooleanExtra(EXTRA_CLIENT_AUTH, false);
        boolean authOffline = getIntent() != null &&
                getIntent().getBooleanExtra(EXTRA_AUTH_OFFLINE, false);
        String controlUrl = getIntent() == null ? null : getIntent().getStringExtra(EXTRA_CONTROL_URL);
        String cameraId = getIntent() == null ? null : getIntent().getStringExtra(EXTRA_CAMERA_ID);
        String profileId = getIntent() == null ? null : getIntent().getStringExtra(EXTRA_PROFILE_ID);
        String manifest = getIntent() == null ? null : getIntent().getStringExtra(EXTRA_MANIFEST);
        byte[] bytes = manifest == null ? new byte[0] : manifest.getBytes(StandardCharsets.UTF_8);
        if (bytes.length == 0 || bytes.length > MAX_MANIFEST_BYTES) {
            throw new IllegalArgumentException("A bounded private acceptance manifest is required");
        }
        try {
            privateManifest = new File(getCacheDir(), "webobs-m3-reference.json").getCanonicalFile();
            File cacheRoot = getCacheDir().getCanonicalFile();
            if (!privateManifest.getPath().startsWith(cacheRoot.getPath() + File.separator)) {
                throw new SecurityException("Acceptance manifest escaped the private cache");
            }
            try (FileOutputStream output = new FileOutputStream(privateManifest, false)) {
                output.write(bytes);
                output.getFD().sync();
            }
            appendApplicationParameters("--probe-manifest " + privateManifest.getAbsolutePath());
            if (backgroundRelease) {
                appendApplicationParameters("--probe-background-release");
            }
            if (reconnect) {
                appendApplicationParameters("--probe-reconnect");
            }
            if (foregroundResume) {
                appendApplicationParameters("--probe-foreground-resume");
            }
            if (clientAuth) {
                if (controlUrl == null || controlUrl.length() > 2048 || cameraId == null ||
                        !cameraId.matches("[A-Za-z0-9._-]{1,64}") || profileId == null ||
                        !profileId.matches("[A-Za-z0-9._-]{1,64}")) {
                    throw new SecurityException("Authorization probe parameters are invalid");
                }
                appendApplicationParameters("--probe-client-auth");
                appendApplicationParameters("--probe-control-url");
                appendApplicationParameters(controlUrl);
                appendApplicationParameters("--probe-camera-id");
                appendApplicationParameters(cameraId);
                appendApplicationParameters("--probe-profile-id");
                appendApplicationParameters(profileId);
                if (authOffline) {
                    appendApplicationParameters("--probe-auth-offline");
                }
            }
        } catch (Exception error) {
            throw new IllegalStateException("The private acceptance manifest could not be staged", error);
        }
        super.onCreate(state);
        if (microphonePermission) {
            Log.i("WebObsProbe", "{\"result\":\"microphone-permission\"," +
                    "\"granted\":" + ensureMicrophonePermission() + "}");
        }
        if (backgroundRelease) {
            KeyStoreBridge.setWakeLock(true);
        }
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        if (intent != null && intent.getBooleanExtra(EXTRA_NETWORK_STATUS, false)) {
            Log.i("WebObsProbe", "{\"result\":\"network-status\",\"status\":\"" +
                    networkStatus() + "\"}");
        }
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        if (privateManifest != null) {
            // This file can contain private endpoint addresses and never survives the gate process.
            privateManifest.delete();
        }
    }
}
