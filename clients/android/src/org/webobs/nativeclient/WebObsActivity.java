package org.webobs.nativeclient;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.media.MediaCodecInfo;
import android.media.MediaCodecList;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.NetworkRequest;
import android.net.Uri;
import android.os.Bundle;
import android.os.PowerManager;

import org.qtproject.qt.android.bindings.QtActivity;

import java.io.File;
import java.io.FileInputStream;
import java.io.OutputStream;
import java.lang.reflect.Method;
import java.util.Locale;
import java.util.concurrent.atomic.AtomicReference;

/** Android-only lifecycle and operating-system boundary for the native client. */
public class WebObsActivity extends QtActivity {
    private static final int REQUEST_MICROPHONE = 1701;
    private static final int REQUEST_EXPORT = 1702;
    private static final long MAX_EXPORT_BYTES = 16L * 1024L * 1024L * 1024L;
    private static final AtomicReference<String> exportStatus = new AtomicReference<>("");
    private static volatile String pendingExportPath;
    private static volatile String networkStatus = "unknown";
    private ConnectivityManager.NetworkCallback networkCallback;

    @Override
    public void onCreate(Bundle state) {
        if (!initializeGStreamer(this)) {
            throw new IllegalStateException("The verified GStreamer Android runtime could not initialize");
        }
        super.onCreate(state);
        registerNetworkObserver();
    }

    @Override
    protected void onPause() {
        KeyStoreBridge.setWakeLock(false);
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        if (networkCallback != null) {
            try {
                ((ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE))
                        .unregisterNetworkCallback(networkCallback);
            } catch (RuntimeException ignored) {
                // The callback may already have been removed by the OS.
            }
        }
        KeyStoreBridge.setWakeLock(false);
        super.onDestroy();
    }

    private static boolean initializeGStreamer(Context context) {
        try {
            Class<?> bridge = Class.forName("org.freedesktop.gstreamer.GStreamer");
            Method initialize = bridge.getMethod("init", Context.class);
            initialize.invoke(null, context);
            return true;
        } catch (ReflectiveOperationException | RuntimeException ignored) {
            return false;
        }
    }

    private void registerNetworkObserver() {
        ConnectivityManager manager =
                (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
        networkCallback = new ConnectivityManager.NetworkCallback() {
            @Override public void onAvailable(Network network) { updateNetworkStatus(manager); }
            @Override public void onLost(Network network) { updateNetworkStatus(manager); }
            @Override public void onCapabilitiesChanged(Network network, NetworkCapabilities caps) {
                updateNetworkStatus(manager);
            }
        };
        manager.registerNetworkCallback(new NetworkRequest.Builder().build(), networkCallback);
        updateNetworkStatus(manager);
    }

    private static void updateNetworkStatus(ConnectivityManager manager) {
        Network active = manager.getActiveNetwork();
        NetworkCapabilities caps = active == null ? null : manager.getNetworkCapabilities(active);
        if (caps == null || !caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)) {
            networkStatus = "offline";
        } else if (caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) {
            networkStatus = "vpn";
        } else if (caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) {
            networkStatus = "wifi";
        } else if (caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)) {
            networkStatus = "ethernet";
        } else if (caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR)) {
            networkStatus = "cellular";
        } else {
            networkStatus = "online";
        }
    }

    public static String networkStatus() {
        return networkStatus;
    }

    public static int hardwareVideoDecoderInstances() {
        int avcInstances = 0;
        int hevcInstances = 0;
        try {
            for (MediaCodecInfo info : new MediaCodecList(MediaCodecList.ALL_CODECS).getCodecInfos()) {
                if (info.isEncoder() || !info.isHardwareAccelerated()) {
                    continue;
                }
                for (String type : info.getSupportedTypes()) {
                    int instances = info.getCapabilitiesForType(type).getMaxSupportedInstances();
                    if (type.equalsIgnoreCase("video/avc"))
                        avcInstances = Math.max(avcInstances, instances);
                    else if (type.equalsIgnoreCase("video/hevc"))
                        hevcInstances = Math.max(hevcInstances, instances);
                }
            }
        } catch (RuntimeException ignored) {
            return 0;
        }
        if (avcInstances > 0 && hevcInstances > 0)
            return Math.min(avcInstances, hevcInstances);
        return Math.max(avcInstances, hevcInstances);
    }

    public static String thermalStatus() {
        Context context = KeyStoreBridge.contextForPlatform();
        if (context == null) {
            return "unknown";
        }
        PowerManager manager = (PowerManager) context.getSystemService(Context.POWER_SERVICE);
        switch (manager.getCurrentThermalStatus()) {
            case PowerManager.THERMAL_STATUS_NONE: return "none";
            case PowerManager.THERMAL_STATUS_LIGHT: return "light";
            case PowerManager.THERMAL_STATUS_MODERATE: return "moderate";
            case PowerManager.THERMAL_STATUS_SEVERE: return "severe";
            case PowerManager.THERMAL_STATUS_CRITICAL: return "critical";
            case PowerManager.THERMAL_STATUS_EMERGENCY: return "emergency";
            case PowerManager.THERMAL_STATUS_SHUTDOWN: return "shutdown";
            default: return "unknown";
        }
    }

    public static boolean ensureMicrophonePermission() {
        Context context = KeyStoreBridge.contextForPlatform();
        if (!(context instanceof Activity)) {
            return false;
        }
        Activity activity = (Activity) context;
        if (activity.checkSelfPermission(Manifest.permission.RECORD_AUDIO)
                == PackageManager.PERMISSION_GRANTED) {
            return true;
        }
        activity.requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQUEST_MICROPHONE);
        return false;
    }

    public static String privateCapturePath(String extension) {
        Context context = KeyStoreBridge.contextForPlatform();
        if (context == null || extension == null ||
                !extension.toLowerCase(Locale.ROOT).matches("mkv|jpg|png|json")) {
            return "";
        }
        File directory = new File(context.getFilesDir(), "captures");
        if ((!directory.isDirectory() && !directory.mkdirs()) || !directory.canWrite()) {
            return "";
        }
        return new File(directory, "webobs-" + System.currentTimeMillis() + "." +
                extension.toLowerCase(Locale.ROOT)).getAbsolutePath();
    }

    public static synchronized boolean exportPrivateCapture(String sourcePath, String mimeType,
                                                             String displayName) {
        Context context = KeyStoreBridge.contextForPlatform();
        if (!(context instanceof WebObsActivity) || sourcePath == null || displayName == null ||
                displayName.contains("/") || displayName.contains("\\") || pendingExportPath != null) {
            return false;
        }
        try {
            File source = new File(sourcePath).getCanonicalFile();
            File root = new File(context.getFilesDir(), "captures").getCanonicalFile();
            if (!source.isFile() || source.length() <= 0 || source.length() > MAX_EXPORT_BYTES ||
                    !source.getPath().startsWith(root.getPath() + File.separator)) {
                return false;
            }
            pendingExportPath = source.getPath();
            exportStatus.set("pending");
            Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT);
            intent.addCategory(Intent.CATEGORY_OPENABLE);
            intent.setType(mimeType == null || mimeType.isEmpty() ?
                    "application/octet-stream" : mimeType);
            intent.putExtra(Intent.EXTRA_TITLE, displayName);
            ((WebObsActivity) context).startActivityForResult(intent, REQUEST_EXPORT);
            return true;
        } catch (Exception ignored) {
            pendingExportPath = null;
            exportStatus.set("failed");
            return false;
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQUEST_EXPORT) {
            return;
        }
        String sourcePath;
        synchronized (WebObsActivity.class) {
            sourcePath = pendingExportPath;
            pendingExportPath = null;
        }
        if (resultCode != RESULT_OK || data == null || data.getData() == null || sourcePath == null) {
            exportStatus.set("cancelled");
            return;
        }
        Uri target = data.getData();
        try (FileInputStream input = new FileInputStream(sourcePath);
             OutputStream output = getContentResolver().openOutputStream(target, "w")) {
            if (output == null) {
                throw new IllegalStateException("document provider returned no output stream");
            }
            byte[] buffer = new byte[128 * 1024];
            int length;
            while ((length = input.read(buffer)) != -1) {
                output.write(buffer, 0, length);
            }
            output.flush();
            exportStatus.set("complete");
        } catch (Exception ignored) {
            exportStatus.set("failed");
        }
    }

    public static String consumeExportStatus() {
        String status = exportStatus.get();
        if (status.equals("complete") || status.equals("failed") || status.equals("cancelled")) {
            exportStatus.compareAndSet(status, "");
        }
        return status;
    }
}
