package io.github.liaoyk001.webobs.android;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.URL;
import javax.net.ssl.HttpsURLConnection;

/** Fixed unauthenticated GitHub endpoint, bounded responses; no token or silent APK installation. */
public final class ReleaseCheck {
    public interface Callback { void complete(Result result); }
    public static final class Result { public final String message; Result(String message) { this.message = message; } }
    private ReleaseCheck() {}
    public static void check(String installedVersion, Callback callback) {
        new Thread(() -> {
            HttpsURLConnection connection = null;
            String message;
            try {
                connection = (HttpsURLConnection) new URL("https://api.github.com/repos/LiaoYK001/Web-Camera-Monitor-Wall/releases/latest").openConnection();
                connection.setInstanceFollowRedirects(false); connection.setConnectTimeout(8000); connection.setReadTimeout(8000);
                connection.setRequestProperty("Accept", "application/vnd.github+json"); connection.setRequestProperty("User-Agent", "WebOBS-Android");
                if (connection.getResponseCode() != 200) throw new IllegalStateException();
                ByteArrayOutputStream bytes = new ByteArrayOutputStream();
                try (InputStream input = connection.getInputStream()) { byte[] buffer = new byte[8192]; int count; while ((count = input.read(buffer)) != -1) { if (bytes.size() + count > 512 * 1024) throw new IllegalStateException(); bytes.write(buffer, 0, count); } }
                JSONObject release = new JSONObject(bytes.toString("UTF-8"));
                if (release.optBoolean("draft") || release.optBoolean("prerelease")) throw new IllegalStateException();
                JSONArray assets = release.optJSONArray("assets"); boolean android = false;
                if (assets != null) for (int index = 0; index < assets.length(); index++) {
                    String name = assets.getJSONObject(index).optString("name");
                    if (name.startsWith("WebOBS-") && name.endsWith("-android-SELF-SIGNED.apk")) android = true;
                }
                message = android ? "GitHub 正式发布包含 Android 安装包。当前安装版本：" + installedVersion + "。请查看发布说明，并使用相同签名的 APK 覆盖安装。" : "当前正式发布尚未提供 Android APK。当前安装版本：" + installedVersion + "。开发测试包可手动覆盖安装，服务器页面随部署更新。";
            } catch (Exception error) { message = "检查更新失败，请确认网络后重试。当前版本仍可继续使用。"; }
            finally { if (connection != null) connection.disconnect(); }
            callback.complete(new Result(message));
        }, "webobs-release-check").start();
    }
}
