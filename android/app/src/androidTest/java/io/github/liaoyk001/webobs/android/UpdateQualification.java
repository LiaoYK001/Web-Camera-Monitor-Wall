package io.github.liaoyk001.webobs.android;

import android.app.DownloadManager;
import android.app.Instrumentation;
import android.content.Context;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.os.ParcelFileDescriptor;
import android.webkit.CookieManager;
import java.io.File;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;

/** Runs only in the separate qualification package; no test entry is included in product APKs. */
public final class UpdateQualification extends Instrumentation {
    private Bundle arguments;
    private Context target;
    private AndroidUpdates updates;
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); this.arguments = arguments; start(); }
    @Override public void onStart() {
        Bundle result = new Bundle(); int code = 0;
        try {
            target = getTargetContext();
            require(target.getPackageName().equals("io.github.liaoyk001.webobs.android.updatequalification"), "Refuse an existing product package");
            String mode = arguments.getString("mode", "cases");
            if (mode.equals("retained")) {
                require(target.getSharedPreferences("connection", 0).getString("qualification", "").equals("retained-v4"), "Connection data lost");
                require(!target.getSharedPreferences("connection", 0).getBoolean("keepScreenOn", true), "Client preference lost");
                String cookies = CookieManager.getInstance().getCookie(arguments.getString("origin"));
                require(cookies != null && cookies.contains("qualification=retained-v4"), "WebView cookie lost");
                require(target.getPackageManager().getPackageInfo(target.getPackageName(), 0).versionName.equals(arguments.getString("installed")), "Wrong installed version");
                result.putString("stream", "PASS: actual installed version, connection, preference and WebView cookie retained\n");
            } else if (mode.equals("cases")) {
                exercise("corrupt", "不完整或摘要");
                exercise("wrong-key", "签名");
                exercise("wrong-package", "包名");
                exercise("next", "包名", "4.0.2");
                exercise("base", "包名", "4.0.0");
                exercise("missing", "下载失败");
                exercise("oversized", "超过声明大小");
                reset(); configure("transient", "4.0.1"); onMain(() -> { updates.download(); updates.foreground(true); });
                require(phase().equals("downloading"), "A temporary status failure removed the live job");
                require(target.getSharedPreferences(AndroidUpdates.STORE, 0).getLong("downloadId", -1) >= 0, "A temporary status failure lost task ownership");
                await("ready"); provider(); dispose();
                Files.delete(AndroidUpdates.readyFile(target).toPath());
                onMain(() -> updates = new AndroidUpdates(target, transport("next")));
                require(phase().equals("error"), "A missing staged APK was offered for installation");
                reset(); configure("slow", "4.0.1"); onMain(() -> { updates.download(); updates.foreground(true); });
                Thread.sleep(500); onMain(() -> updates.cancel()); Thread.sleep(1500);
                require(phase().equals("available"), "Cancelled download became ready");
                require(!target.getSharedPreferences(AndroidUpdates.STORE, 0).getBoolean("ready", false), "Cancellation published update");
                dispose();
                result.putString("stream", "PASS: real DownloadManager corruption, signature, package/version, downgrade, missing attachment, oversized, temporary query failure, missing staged APK and cancellation cases\n");
            } else if (mode.equals("start-partial")) {
                reset(); configure("slow", "4.0.1"); onMain(() -> updates.download());
                require(target.getSharedPreferences(AndroidUpdates.STORE, 0).getLong("downloadId", -1) >= 0, "System task not persisted");
                long id = target.getSharedPreferences(AndroidUpdates.STORE, 0).getLong("downloadId", -1);
                UpdateDownloads.Status live = transport("slow").status(id);
                require(live != null && live.phase != DownloadManager.STATUS_FAILED, "System task is missing or failed");
                dispose(); result.putString("stream", "PASS: live system download persisted before owner process exit\n");
            } else if (mode.equals("resume")) {
                onMain(() -> updates = new AndroidUpdates(target, transport("slow")));
                onMain(() -> updates.foreground(true)); await("ready"); provider(); dispose();
                result.putString("stream", "PASS: actual system task recovered and APK verified after owner process restart\n");
            } else if (mode.equals("prepare")) {
                reset(); configure("next", arguments.getString("version")); onMain(() -> { updates.download(); updates.foreground(true); }); await("ready"); provider();
                target.getSharedPreferences("connection", 0).edit().putString("server", arguments.getString("origin"))
                        .putString("qualification", "retained-v4").putBoolean("keepScreenOn", false).commit();
                onMain(() -> { CookieManager.getInstance().setCookie(arguments.getString("origin"), "qualification=retained-v4; Path=/; SameSite=Strict"); CookieManager.getInstance().flush(); });
                dispose(); result.putString("stream", "PASS: verified same-key APK prepared for actual system installer\n");
            } else throw new AssertionError("Unknown qualification mode");
        } catch (Throwable error) {
            result.putString("stream", "FAIL: " + error.getClass().getSimpleName() + ": " + error.getMessage() + "\n"); code = 1;
        } finally { if (updates != null) onMain(() -> updates.disposeForQualification()); }
        finish(code, result);
    }
    private void onMain(Runnable action) { runOnMainSync(action); }
    private void dispose() { onMain(() -> { updates.disposeForQualification(); updates = null; }); }
    private void reset() throws Exception {
        if (updates != null) dispose();
        SharedPreferences prefs = target.getSharedPreferences(AndroidUpdates.STORE, 0);
        long id = prefs.getLong("downloadId", -1); if (id >= 0) target.getSystemService(DownloadManager.class).remove(id);
        prefs.edit().clear().putBoolean("autoCheck", false).putBoolean("autoDownload", false).putBoolean("wifiOnly", false).commit();
        Files.deleteIfExists(AndroidUpdates.readyFile(target).toPath());
    }
    private ReleaseAsset candidate(String version, String route) throws Exception {
        String prefix = route.equals("wrong-key") || route.equals("wrong-package") || route.equals("base") ? route : "next";
        String digest = arguments.getString(prefix + "Hash"); long size = Long.parseLong(arguments.getString(prefix + "Size"));
        String tag = "v" + version, name = "WebOBS-" + version + "-android-SELF-SIGNED.apk";
        ReleaseAsset asset = ReleaseAsset.parse(tag, name, ReleaseOffer.REPOSITORY + "/releases/download/" + tag + "/" + name, "sha256:" + digest, size, "uploaded");
        require(asset != null, "Invalid qualification identity"); return asset;
    }
    private void configure(String route, String version) throws Exception {
        ReleaseAsset asset = candidate(version, route);
        onMain(() -> { updates = new AndroidUpdates(target, transport(route)); updates.asset = asset; updates.phase = "available"; });
    }
    private void exercise(String route, String failure) throws Exception {
        exercise(route, failure, "4.0.1");
    }
    private void exercise(String route, String failure, String version) throws Exception {
        reset(); configure(route, version); onMain(() -> { updates.download(); updates.foreground(true); }); await("error");
        String[] detail = {""}; onMain(() -> detail[0] = updates.message);
        require(detail[0].contains(failure), route + " returned unexpected failure: " + detail[0]);
        require(!target.getSharedPreferences(AndroidUpdates.STORE, 0).getBoolean("ready", false), route + " published rejected APK");
    }
    private String phase() { String[] value = {""}; onMain(() -> value[0] = updates.phase); return value[0]; }
    private void await(String expected) throws Exception {
        long deadline = System.currentTimeMillis() + 45000;
        while (System.currentTimeMillis() < deadline) { if (phase().equals(expected)) return; Thread.sleep(100); }
        String[] message = {""}; onMain(() -> message[0] = updates.message);
        throw new AssertionError("Expected " + expected + ", got " + phase() + ": " + message[0]);
    }
    private void provider() throws Exception {
        String hash = target.getSharedPreferences(AndroidUpdates.STORE, 0).getString("sha256", "");
        Uri uri = Uri.parse("content://" + target.getPackageName() + ".updates/apk/" + hash);
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream input = target.getContentResolver().openInputStream(uri)) {
            byte[] bytes = new byte[8192]; int count; while ((count = input.read(bytes)) != -1) digest.update(bytes, 0, count);
        }
        StringBuilder received = new StringBuilder(); for (byte value : digest.digest()) received.append(String.format("%02x", value & 255));
        require(received.toString().equals(hash), "Provider returned another file");
        for (String bad : new String[]{uri.toString() + "/../x", uri + "?file=x", "content://" + target.getPackageName() + ".updates/apk/" + "0".repeat(64)}) {
            boolean rejected = false; try (ParcelFileDescriptor ignored = target.getContentResolver().openFileDescriptor(Uri.parse(bad), "r")) { } catch (java.io.FileNotFoundException error) { rejected = true; }
            require(rejected, "Provider accepted unsafe URI");
        }
        boolean readOnly = false;
        try (ParcelFileDescriptor ignored = target.getContentResolver().openFileDescriptor(uri, "rw")) { } catch (java.io.FileNotFoundException error) { readOnly = true; }
        require(readOnly, "Provider allowed writes");
    }
    private UpdateDownloads transport(String route) {
        UpdateDownloads delegate = new UpdateDownloads.SystemDownloads(target);
        boolean[] queryFailed = {false};
        return new UpdateDownloads() {
            @Override public long start(ReleaseAsset asset, boolean wifiOnly) throws java.io.IOException {
                // Test APK only: use an ADB-reversed fixture with the production system download service.
                File destination = new File(target.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), "webobs-updates/update.apk");
                destination.getParentFile().mkdirs(); Files.deleteIfExists(destination.toPath());
                DownloadManager.Request request = new DownloadManager.Request(Uri.parse(arguments.getString("origin") + "/" + route));
                request.setDestinationUri(Uri.fromFile(destination)).setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE);
                return target.getSystemService(DownloadManager.class).enqueue(request);
            }
            @Override public long recover(ReleaseAsset asset) { return delegate.recover(asset); }
            @Override public Status status(long id) {
                if (route.equals("transient") && !queryFailed[0]) { queryFailed[0] = true; throw new IllegalStateException("Temporary qualification status failure"); }
                return delegate.status(id);
            }
            @Override public InputStream open(long id) throws java.io.IOException { return delegate.open(id); }
            @Override public void remove(long id) { delegate.remove(id); }
        };
    }
    private static void require(boolean condition, String message) { if (!condition) throw new AssertionError(message); }
}
