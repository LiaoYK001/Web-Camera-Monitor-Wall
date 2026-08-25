package org.webobs.nativeclient;

import android.os.Bundle;
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
    protected void onDestroy() {
        super.onDestroy();
        if (privateManifest != null) {
            // This file can contain private endpoint addresses and never survives the gate process.
            privateManifest.delete();
        }
    }
}
