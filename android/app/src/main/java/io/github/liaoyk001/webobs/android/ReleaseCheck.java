package io.github.liaoyk001.webobs.android;

import org.json.JSONArray;
import org.json.JSONObject;
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
        public final ReleaseAsset asset;
        public final boolean failed;
        Result(String message, String releaseUrl, boolean available, ReleaseAsset asset, boolean failed) {
            this.message = message; this.releaseUrl = releaseUrl; this.available = available; this.asset = asset; this.failed = failed;
        }
    }
    private ReleaseCheck() {}
    public static void check(String installedVersion, Callback callback) {
        new Thread(() -> {
            HttpsURLConnection connection = null;
            Result result;
            String failure = "检查更新失败，请确认网络后重试。当前版本仍可继续使用。";
            long deadline = System.nanoTime() + 20000000000L;
            try {
                connection = (HttpsURLConnection) new URL("https://api.github.com/repos/LiaoYK001/Web-Camera-Monitor-Wall/releases?per_page=20").openConnection();
                connection.setInstanceFollowRedirects(false); connection.setConnectTimeout(8000); connection.setReadTimeout(8000);
                connection.setRequestProperty("Accept", "application/vnd.github+json"); connection.setRequestProperty("User-Agent", "WebOBS-Android");
                int status = connection.getResponseCode();
                if (status == 403 || status == 429) failure = "GitHub 暂时限制更新检查，请稍后再试或查看发布记录。当前客户端可继续使用。";
                if (status != 200) throw new IllegalStateException();
                byte[] bytes;
                try (InputStream input = connection.getInputStream()) { bytes = ReleaseBody.read(input, deadline); }
                JSONArray releases = new JSONArray(new String(bytes, java.nio.charset.StandardCharsets.UTF_8));
                List<ReleaseOffer.Candidate> candidates = new ArrayList<>();
                for (int index = 0; index < Math.min(20, releases.length()); index++) {
                    JSONObject release = releases.getJSONObject(index);
                    JSONArray assets = release.optJSONArray("assets"); List<String> names = new ArrayList<>(); List<ReleaseAsset> downloads = new ArrayList<>();
                    if (assets != null) for (int asset = 0; asset < Math.min(128, assets.length()); asset++) {
                        JSONObject data = assets.getJSONObject(asset); names.add(data.optString("name"));
                        ReleaseAsset download = ReleaseAsset.parse(release.optString("tag_name"), data.optString("name"),
                                data.optString("browser_download_url"), data.optString("digest"), data.optLong("size"), data.optString("state"));
                        if (download != null) downloads.add(download);
                    }
                    candidates.add(new ReleaseOffer.Candidate(release.optString("tag_name"), release.optBoolean("draft"), release.optBoolean("prerelease"), names, release.optString("body"), downloads));
                }
                ReleaseOffer offer = ReleaseOffer.select(installedVersion, candidates);
                result = new Result(offer.message, offer.releaseUrl, offer.available, offer.asset, false);
            } catch (Exception error) { result = new Result(failure, ReleaseOffer.REPOSITORY + "/releases", false, null, true); }
            finally { if (connection != null) connection.disconnect(); }
            callback.complete(result);
        }, "webobs-release-check").start();
    }
}
