package io.github.liaoyk001.webobs.android;

/** Exact product attachment identity. Feed data never supplies arbitrary download destinations. */
public final class ReleaseAsset {
    public static final long MAX_BYTES = 128L * 1024 * 1024;
    public final String tag, version, name, url, sha256;
    public final long size, versionCode;

    private ReleaseAsset(String tag, ReleaseVersion version, String name, String url, String sha256, long size) {
        this.tag = tag; this.version = version.toString(); this.name = name;
        this.url = url; this.sha256 = sha256; this.size = size;
        this.versionCode = version.major * 1000000L + version.minor * 1000L + version.patch;
    }

    public static ReleaseAsset parse(String tag, String name, String url, String digest, long size, String state) {
        ReleaseVersion version = ReleaseVersion.tag(tag);
        if (version == null || version.major < 4 || version.minor > 999 || version.patch > 999
                || version.major * 1000000L + version.minor * 1000L + version.patch > 2100000000L) return null;
        String expected = "WebOBS-" + version + "-android-SELF-SIGNED.apk";
        if (!expected.equals(name) || !(ReleaseOffer.REPOSITORY + "/releases/download/" + tag + "/" + expected).equals(url)
                || digest == null || !digest.matches("sha256:[a-fA-F0-9]{64}")
                || size <= 0 || size > MAX_BYTES || !"uploaded".equals(state)) return null;
        return new ReleaseAsset(tag, version, name, url, digest.substring(7).toLowerCase(java.util.Locale.ROOT), size);
    }
}
