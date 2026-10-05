package io.github.liaoyk001.webobs.android;

import android.app.DownloadManager;
import android.content.Context;
import android.content.SharedPreferences;
import android.os.Handler;
import android.os.Looper;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Application-owned update state. No Activity, WebView, product cookie or account is retained. */
public final class AndroidUpdates {
    public interface Listener { void changed(); }
    public interface InstallCheck { void complete(boolean valid); }
    static final String STORE = "android-updates";
    private static final long CHECK_INTERVAL = 6L * 60 * 60 * 1000;
    private static AndroidUpdates instance;
    private final Context context;
    private final SharedPreferences store;
    private final UpdateDownloads downloads;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final Set<Listener> listeners = new LinkedHashSet<>();
    private long id = -1;
    private volatile int generation;
    private boolean foreground, checking;
    private int queryFailures;
    public String phase = "idle", message = "尚未检查更新。", releaseUrl = ReleaseOffer.REPOSITORY + "/releases";
    public int percent;
    public ReleaseAsset asset;
    private final Runnable poll = () -> reconcile();
    private final Runnable automatic = () -> check(false);

    public static synchronized AndroidUpdates get(Context context) {
        if (instance == null) instance = new AndroidUpdates(context.getApplicationContext(), null);
        return instance;
    }
    // Injection is restricted to same-package native tests; no renderer/Intent configuration.
    AndroidUpdates(Context context, UpdateDownloads downloads) {
        this.context = context; this.downloads = downloads == null ? new UpdateDownloads.SystemDownloads(context) : downloads;
        store = context.getSharedPreferences(STORE, Context.MODE_PRIVATE);
        asset = ReleaseAsset.parse(store.getString("tag", ""), store.getString("name", ""), store.getString("url", ""),
                "sha256:" + store.getString("sha256", ""), store.getLong("size", 0), "uploaded");
        if (asset == null) return;
        try {
            if (context.getPackageManager().getPackageInfo(context.getPackageName(), 0).getLongVersionCode() >= asset.versionCode) {
                this.downloads.remove(store.getLong("downloadId", -1));
                store.edit().remove("tag").putBoolean("pending", false).putBoolean("ready", false).apply();
                asset = null; message = "已完成客户端更新，服务器与账号配置保留。";
                worker.execute(() -> { try { Files.deleteIfExists(readyFile(context).toPath()); } catch (IOException ignored) { } });
                return;
            }
        } catch (android.content.pm.PackageManager.NameNotFoundException | RuntimeException ignored) { }
        releaseUrl = ReleaseOffer.REPOSITORY + "/releases/tag/" + asset.tag;
        if (store.getBoolean("ready", false)) {
            if (!readyFile(context).isFile() || readyFile(context).length() != asset.size) {
                store.edit().putBoolean("ready", false).apply(); phase = "error";
                message = "已下载更新文件丢失或不完整，请重新下载。当前客户端可继续使用。"; return;
            }
            phase = "ready"; message = "已下载 " + asset.version + "，安装前会再次校验。";
        } else if (store.getBoolean("pending", false)) {
            id = store.getLong("downloadId", -1);
            if (id < 0) { try { id = this.downloads.recover(asset); } catch (RuntimeException ignored) { } }
            phase = "downloading"; message = "正在恢复系统下载任务…";
        } else { phase = "available"; message = "可下载更新 " + asset.version + "。"; }
    }
    public boolean setting(String name) { return store.getBoolean(name, true); }
    public void setting(String name, boolean value) {
        if (!Set.of("autoCheck", "autoDownload", "wifiOnly").contains(name)) return;
        store.edit().putBoolean(name, value).apply();
        if (name.equals("autoCheck")) { handler.removeCallbacks(automatic); if (value && foreground) check(false); }
        announce();
    }
    public void listen(Listener listener) { listeners.add(listener); listener.changed(); }
    public void unlisten(Listener listener) { listeners.remove(listener); }
    void disposeForQualification() { synchronized (this) { generation++; } foreground(false); listeners.clear(); worker.shutdownNow(); }
    private void announce() { for (Listener listener : listeners.toArray(new Listener[0])) listener.changed(); }
    public void foreground(boolean value) {
        foreground = value; handler.removeCallbacks(poll); handler.removeCallbacks(automatic);
        if (value) { reconcile(); check(false); }
    }
    public void check(boolean manual) {
        if (checking || phase.equals("downloading") || phase.equals("verifying") || phase.equals("ready")) return;
        long now = System.currentTimeMillis(), last = store.getLong("lastCheck", 0);
        if (!manual && (!foreground || !setting("autoCheck"))) return;
        if (!manual && now >= last && now - last < CHECK_INTERVAL) {
            handler.removeCallbacks(automatic); handler.postDelayed(automatic, CHECK_INTERVAL - (now - last)); return;
        }
        String installed;
        try { installed = context.getPackageManager().getPackageInfo(context.getPackageName(), 0).versionName; }
        catch (android.content.pm.PackageManager.NameNotFoundException error) { fail("无法读取当前版本，请重启客户端后重试。"); return; }
        checking = true; phase = "checking"; message = "正在检查 GitHub 正式更新…"; announce();
        int token = generation;
        ReleaseCheck.check(installed, result -> handler.post(() -> {
            checking = false;
            if (token != generation) return;
            store.edit().putLong("lastCheck", System.currentTimeMillis()).apply();
            releaseUrl = result.releaseUrl; message = result.message;
            phase = result.failed ? "error" : result.available ? "available" : "idle";
            asset = result.asset;
            if (asset != null && !save(false, false, -1)) { fail("无法保存更新信息，请检查存储空间后重试。"); return; }
            if (asset == null && !result.failed) store.edit().remove("tag").putBoolean("ready", false).putBoolean("pending", false).apply();
            announce();
            if (asset != null && !manual && setting("autoDownload") && !asset.sha256.equals(store.getString("deferred", ""))) download();
            if (foreground && setting("autoCheck")) { handler.removeCallbacks(automatic); handler.postDelayed(automatic, CHECK_INTERVAL); }
        }));
    }
    public void download() {
        if (asset == null || checking || phase.equals("downloading") || phase.equals("verifying") || phase.equals("ready")) return;
        try {
            generation++;
            downloads.remove(id); id = -1;
            if (!save(false, true, -1)) throw new IOException("Update metadata cannot be saved");
            id = downloads.start(asset, setting("wifiOnly"));
            if (!save(false, true, id)) { downloads.remove(id); throw new IOException("Download ownership cannot be saved"); }
            phase = "downloading"; percent = 0; message = "已交给系统下载 " + asset.version + "；安装仍需你确认。"; announce();
            if (foreground) reconcile();
        } catch (IOException | RuntimeException error) { fail("无法启动更新下载，请检查存储空间与系统下载管理器后重试。"); }
    }
    private void reconcile() {
        handler.removeCallbacks(poll);
        if (!phase.equals("downloading")) return;
        try {
            if (id < 0) { id = downloads.recover(asset); if (id >= 0 && !save(false, true, id)) throw new IllegalStateException("Download recovery cannot be saved"); }
            UpdateDownloads.Status state = id < 0 ? null : downloads.status(id);
            queryFailures = 0;
            if (state == null) { fail("系统下载任务已移除，请重新下载。当前客户端可继续使用。"); return; }
            if (state.received > asset.size || state.total > asset.size || state.received < 0) {
                downloads.remove(id); fail("更新文件超过声明大小，下载已停止，请联系维护者核对发布附件。"); return;
            }
            percent = (int) Math.min(100, state.received * 100 / asset.size);
            if (state.phase == DownloadManager.STATUS_SUCCESSFUL) { verifyDownloaded(); return; }
            if (state.phase == DownloadManager.STATUS_FAILED) {
                String reason = state.reason == DownloadManager.ERROR_INSUFFICIENT_SPACE ? "存储空间不足，请释放空间后重试。"
                        : state.reason == DownloadManager.ERROR_FILE_ERROR ? "无法保存更新文件，请检查存储空间后重试。"
                        : "更新下载失败，请确认网络与发布附件后重试。";
                fail(reason + " 当前客户端可继续使用。"); return;
            }
            message = state.phase == DownloadManager.STATUS_PAUSED ? "系统正在等待网络或重试；仅 Wi-Fi 策略遵循下载开始时的设置。"
                    : "正在下载 " + asset.version + "：" + percent + "%（可取消）";
            announce();
            if (foreground) handler.postDelayed(poll, 1200);
        } catch (RuntimeException error) {
            queryFailures = Math.min(5, queryFailures + 1);
            message = "系统下载状态暂不可用，任务已保留；稍后自动重试，也可取消后重新下载。"; announce();
            if (foreground) handler.postDelayed(poll, Math.min(30000, 1200L << queryFailures));
        }
    }
    private boolean save(boolean ready, boolean pending, long downloadId) {
        return store.edit().putString("tag", asset.tag).putString("name", asset.name).putString("url", asset.url)
                .putString("sha256", asset.sha256).putLong("size", asset.size).putLong("downloadId", downloadId)
                .putBoolean("ready", ready).putBoolean("pending", pending).commit();
    }
    static File readyFile(Context context) { return new File(context.getFilesDir(), "updates/ready.apk"); }
    private void verifyDownloaded() {
        phase = "verifying"; message = "正在校验文件、版本与当前安装签名…"; announce();
        ReleaseAsset candidate = asset; long downloadId = id; int token = generation;
        worker.execute(() -> {
            File temporary = new File(context.getFilesDir(), "updates/ready.part"), ready = readyFile(context);
            String errorMessage = null;
            try {
                if (!ready.getParentFile().isDirectory() && !ready.getParentFile().mkdirs()) throw new IOException("Update storage unavailable");
                try (InputStream input = downloads.open(downloadId)) { ApkIntegrity.copy(input, temporary, candidate); }
                ApkVerifier.verifyIdentity(context, temporary, candidate);
                synchronized (this) {
                    if (token != generation) { Files.deleteIfExists(temporary.toPath()); return; }
                    Files.move(temporary.toPath(), ready.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
                }
            } catch (IOException | RuntimeException error) {
                errorMessage = error instanceof ApkIntegrity.Rejected ? error.getMessage() : "无法校验或保存更新，请检查存储空间并重新下载。";
                try { Files.deleteIfExists(temporary.toPath()); } catch (IOException ignored) { }
            }
            String failure = errorMessage;
            handler.post(() -> {
                if (token != generation) return;
                if (failure != null) { fail(failure); return; }
                if (!save(true, false, -1)) { fail("更新校验完成，但无法保存状态，请重启客户端后重试。"); return; }
                try { downloads.remove(downloadId); } catch (RuntimeException ignored) { }
                id = -1; percent = 100; phase = "ready";
                message = "更新 " + candidate.version + " 已校验。点击安装更新后仍需系统确认。"; announce();
            });
        });
    }
    public void verifyForInstall(InstallCheck callback) {
        if (!phase.equals("ready") || asset == null) { callback.complete(false); return; }
        phase = "verifying"; message = "安装前再次校验更新…"; announce();
        ReleaseAsset candidate = asset; int token = generation;
        worker.execute(() -> {
            String failure = null;
            try { ApkVerifier.verify(context, readyFile(context), candidate); }
            catch (IOException | RuntimeException error) { failure = error instanceof ApkIntegrity.Rejected ? error.getMessage() : "更新文件无法校验，请重新下载。"; }
            String result = failure;
            handler.post(() -> {
                if (token != generation) { callback.complete(false); return; }
                if (result != null) { fail(result); callback.complete(false); return; }
                phase = "ready"; message = "更新已校验，等待你确认安装。"; announce(); callback.complete(true);
            });
        });
    }
    public void cancel() {
        synchronized (this) { generation++; }
        handler.removeCallbacks(poll);
        if (asset != null) store.edit().putString("deferred", asset.sha256).apply();
        try { downloads.remove(id); } catch (RuntimeException ignored) { }
        id = -1;
        store.edit().putBoolean("pending", false).putBoolean("ready", false).putLong("downloadId", -1).apply();
        // The serial worker owns its partial file and observes generation before publication.
        worker.execute(() -> { try { Files.deleteIfExists(readyFile(context).toPath()); } catch (IOException ignored) { } });
        phase = asset == null ? "idle" : "available"; percent = 0; message = "已取消本次更新；可稍后手动重新下载。"; announce();
    }
    private void fail(String detail) {
        handler.removeCallbacks(poll);
        try { downloads.remove(id); } catch (RuntimeException ignored) { }
        id = -1;
        if (asset != null) store.edit().putString("deferred", asset.sha256).apply();
        store.edit().putBoolean("pending", false).putBoolean("ready", false).putLong("downloadId", -1).apply();
        phase = "error"; message = detail; announce();
    }
}
