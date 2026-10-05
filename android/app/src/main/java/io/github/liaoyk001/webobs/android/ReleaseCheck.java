package io.github.liaoyk001.webobs.android;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.URL;
import java.util.ArrayList;
import java.util.List;
import javax.net.ssl.HttpsURLConnection;

/** Fixed unauthenticated GitHub endpoint, bounded responses; no token or silent APK installation. */
public final class ReleaseCheck {
    public interface Callback { void complete(Result result); }
    public static final class Result {
        public final String message, releaseUrl;
        public final boolean available;
        Result(String message, String releaseUrl, boolean available) { this.message = message; this.releaseUrl = releaseUrl; this.available = available; }
    }
    private ReleaseCheck() {}
    public static void check(String installedVersion, Callback callback) {
        new Thread(() -> {
            HttpsURLConnection connection = null;
            Result result;
            try {
                connection = (HttpsURLConnection) new URL("https://api.github.com/repos/LiaoYK001/Web-Camera-Monitor-Wall/releases?per_page=20").openConnection();
                connection.setInstanceFollowRedirects(false); connection.setConnectTimeout(8000); connection.setReadTimeout(8000);
                connection.setRequestProperty("Accept", "application/vnd.github+json"); connection.setRequestProperty("User-Agent", "WebOBS-Android");
                if (connection.getResponseCode() != 200) throw new IllegalStateException();
                ByteArrayOutputStream bytes = new ByteArrayOutputStream();
                try (InputStream input = connection.getInputStream()) { byte[] buffer = new byte[8192]; int count; while ((count = input.read(buffer)) != -1) { if (bytes.size() + count > 512 * 1024) throw new IllegalStateException(); bytes.write(buffer, 0, count); } }
                JSONArray releases = new JSONArray(bytes.toString("UTF-8"));
                List<ReleaseOffer.Candidate> candidates = new ArrayList<>();
                for (int index = 0; index < Math.min(20, releases.length()); index++) {
                    JSONObject release = releases.getJSONObject(index);
                    JSONArray assets = release.optJSONArray("assets"); List<String> names = new ArrayList<>();
                    if (assets != null) for (int asset = 0; asset < assets.length(); asset++) names.add(assets.getJSONObject(asset).optString("name"));
                    candidates.add(new ReleaseOffer.Candidate(release.optString("tag_name"), release.optBoolean("draft"), release.optBoolean("prerelease"), names, release.optString("body")));
                }
                ReleaseOffer offer = ReleaseOffer.select(installedVersion, candidates);
                result = new Result(offer.message, offer.releaseUrl, offer.available);
            } catch (Exception error) { result = new Result("检查更新失败，请确认网络后重试。当前版本仍可继续使用。", ReleaseOffer.REPOSITORY + "/releases", false); }
            finally { if (connection != null) connection.disconnect(); }
            callback.complete(result);
        }, "webobs-release-check").start();
    }
}
