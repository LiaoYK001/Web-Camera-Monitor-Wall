package io.github.liaoyk001.webobs.android;

import java.util.List;

/** Select the newest stable APK, even when a newer backend-only release exists. */
public final class ReleaseOffer {
    public static final String REPOSITORY = "https://github.com/LiaoYK001/Web-Camera-Monitor-Wall";
    public static final class Candidate {
        public final String tag, notes;
        public final boolean draft, prerelease;
        public final List<String> assets;
        public final List<ReleaseAsset> downloads;
        public Candidate(String tag, boolean draft, boolean prerelease, List<String> assets, String notes) {
            this(tag, draft, prerelease, assets, notes, List.of());
        }
        public Candidate(String tag, boolean draft, boolean prerelease, List<String> assets, String notes, List<ReleaseAsset> downloads) {
            this.tag = tag; this.draft = draft; this.prerelease = prerelease; this.assets = assets; this.notes = notes;
            this.downloads = downloads;
        }
    }
    public final String message, releaseUrl;
    public final boolean available;
    public final ReleaseAsset asset;
    private ReleaseOffer(String message, String releaseUrl, boolean available) {
        this(message, releaseUrl, available, null);
    }
    private ReleaseOffer(String message, String releaseUrl, boolean available, ReleaseAsset asset) {
        this.message = message; this.releaseUrl = releaseUrl; this.available = available; this.asset = asset;
    }
    public static ReleaseOffer select(String installedVersion, List<Candidate> releases) {
        ReleaseVersion installed = ReleaseVersion.installed(installedVersion), newest = null;
        Candidate selected = null;
        for (Candidate candidate : releases) {
            ReleaseVersion version = ReleaseVersion.tag(candidate.tag);
            if (candidate.draft || candidate.prerelease || version == null) continue;
            String apk = "WebOBS-" + version + "-android-SELF-SIGNED.apk";
            if (candidate.assets.contains(apk) && (newest == null || version.compareTo(newest) > 0)) {
                newest = version; selected = candidate;
            }
        }
        String current = "当前 APK：" + installedVersion + "。";
        if (selected == null) return new ReleaseOffer(current + "最近 20 个发布中没有可用的正式 Android APK。服务器页面随后端更新；开发测试 APK 不进入正式更新源。", REPOSITORY + "/releases", false);
        String url = REPOSITORY + "/releases/tag/" + selected.tag;
        if (installed == null) return new ReleaseOffer(current + "无法比较本机版本，请查看正式发布说明后手动核对。", url, false);
        if (newest.compareTo(installed) <= 0) return new ReleaseOffer(current + "最新正式 Android APK：" + newest + "。未发现更高版本，无需更新。", url, false);
        String notes = selected.notes == null ? "" : selected.notes;
        if (notes.length() > 4000) notes = notes.substring(0, 4000) + "\n…完整说明见发布页面。";
        ReleaseAsset asset = null;
        for (ReleaseAsset download : selected.downloads) if (download != null && download.tag.equals(selected.tag)) { asset = download; break; }
        return new ReleaseOffer(current + "发现" + newest.updateLabel(installed) + " " + newest + "。\n"
                + (asset == null ? "发布缺少可验证的 APK 摘要或下载信息，请从发布页面核对后手动下载。" : "可在客户端内下载并校验 APK，安装仍由你和系统确认。")
                + "使用相同签名覆盖安装以保留服务器、账号与偏好。"
                + (notes.isEmpty() ? "" : "\n\n发布说明：\n" + notes), url, true, asset);
    }
    private ReleaseOffer() { throw new AssertionError(); }
}
