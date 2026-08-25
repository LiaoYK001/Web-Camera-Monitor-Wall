package org.webobs.nativeclient.acceptance;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.ComponentName;
import android.content.Intent;
import android.os.Bundle;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

/** Private-lab driver. The APK must be signed by the same certificate as the client. */
public final class WebObsAcceptanceInstrumentation extends Instrumentation {
    private Bundle arguments;

    @Override
    public void onCreate(Bundle suppliedArguments) {
        arguments = suppliedArguments == null ? new Bundle() : suppliedArguments;
        start();
    }

    @Override
    public void onStart() {
        Bundle result = new Bundle();
        try {
            String rawPath = arguments.getString("manifestPath", "");
            File manifest = new File(rawPath).getCanonicalFile();
            File permittedRoot = new File("/data/local/tmp").getCanonicalFile();
            if (!manifest.getPath().startsWith(permittedRoot.getPath() + File.separator) ||
                    !manifest.getName().matches("webobs-m3-[0-9a-f]{16}\\.json") ||
                    !manifest.isFile() || manifest.length() <= 0 || manifest.length() > 1024 * 1024) {
                throw new SecurityException("The private manifest path is outside the bounded lab exchange");
            }
            String document = Files.readString(manifest.toPath(), StandardCharsets.UTF_8);
            Intent intent = new Intent();
            intent.setComponent(new ComponentName("org.webobs.nativeclient",
                    "org.webobs.nativeclient.WebObsProbeActivity"));
            intent.putExtra("org.webobs.nativeclient.extra.PROBE_MANIFEST", document);
            intent.putExtra("org.webobs.nativeclient.extra.PROBE_BACKGROUND_RELEASE",
                    arguments.getString("backgroundRelease", "false").equals("true"));
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
            Activity activity = startActivitySync(intent);
            if (activity == null) {
                throw new IllegalStateException("The signature-protected probe did not start");
            }
            result.putString("webobs", "started");
            finish(Activity.RESULT_OK, result);
        } catch (Exception error) {
            result.putString("webobs", "failed:" + error.getClass().getSimpleName());
            finish(Activity.RESULT_CANCELED, result);
        }
    }
}
