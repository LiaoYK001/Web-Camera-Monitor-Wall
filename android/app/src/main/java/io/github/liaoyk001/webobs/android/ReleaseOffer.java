package io.github.liaoyk001.webobs.android;

import java.util.List;

/** Select the newest stable APK, even when a newer backend-only release exists. */
public final class ReleaseOffer {
    public static final String REPOSITORY = "https://github.com/LiaoYK001/Web-Camera-Monitor-Wall";
    public static final class Candidate {
        public final String tag, notes;
        public final boolean draft, prerelease;
        public final List<String> assets;
        public Candidate(String tag, boolean draft, boolean prerelease, List<String> assets, String notes) {
            this.tag = tag; this.draft = draft; this.prerelease = prerelease; this.assets = assets; this.notes = notes;
        }
    }
    public final String message, releaseUrl;
    public final boolean available;
    private ReleaseOffer(String message, String releaseUrl, boolean available) {
        this.message = message; this.releaseUrl = releaseUrl; this.available = available;
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
        return new ReleaseOffer(current + "发现" + newest.updateLabel(installed) + " " + newest + "。\n"
                + "请从该发布页面下载 APK，并使用相同签名覆盖安装以保留服务器、账号与偏好。安装由你确认。"
                + (notes.isEmpty() ? "" : "\n\n发布说明：\n" + notes), url, true);
    }
    private ReleaseOffer() { throw new AssertionError(); }
}
