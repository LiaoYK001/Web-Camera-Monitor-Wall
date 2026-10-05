package io.github.liaoyk001.webobs.android;

import org.junit.Test;
import static org.junit.Assert.*;
import java.io.ByteArrayInputStream;
import java.io.File;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.List;

public class ApkIntegrityTest {
    private final byte[] bytes = "bounded APK fixture".getBytes(java.nio.charset.StandardCharsets.UTF_8);
    private ReleaseAsset asset(String tag, String url, String digest, long size) {
        ReleaseVersion version = ReleaseVersion.tag(tag);
        return ReleaseAsset.parse(tag, "WebOBS-" + version + "-android-SELF-SIGNED.apk", url, digest, size, "uploaded");
    }
    private String url(String tag) { return ReleaseOffer.REPOSITORY + "/releases/download/" + tag + "/WebOBS-" + ReleaseVersion.tag(tag) + "-android-SELF-SIGNED.apk"; }
    private String digest() throws Exception {
        StringBuilder value = new StringBuilder("sha256:");
        for (byte item : MessageDigest.getInstance("SHA-256").digest(bytes)) value.append(String.format("%02x", item & 255));
        return value.toString();
    }
    @Test public void acceptsExactBoundedProductAsset() throws Exception {
        ReleaseAsset valid = asset("v4.0.10", url("v4.0.10"), digest(), bytes.length);
        assertNotNull(valid); assertEquals(4000010, valid.versionCode);
        assertNotNull(asset("v4.0", url("v4.0"), digest(), bytes.length));
        for (String unsafe : List.of(url("v4.0.10") + "?token=x", url("v4.0.10") + "#x",
                url("v4.0.10").replace("https:", "http:"), url("v4.0.10").replace("github.com/", "github.com.evil.invalid/"),
                url("v4.0.10").replace("github.com/", "user:pass@github.com/"), url("v4.0.10").replace("github.com/", "github.com:443/"), url("v4.0.9"))) {
            assertNull(asset("v4.0.10", unsafe, digest(), bytes.length));
        }
    }
    @Test public void rejectsMissingDigestSizeDevelopmentAndUnrepresentableVersions() throws Exception {
        assertNull(asset("v4.0.1", url("v4.0.1"), "", bytes.length));
        assertNull(asset("v4.0.1", url("v4.0.1"), "sha256:" + "0".repeat(63), bytes.length));
        assertNull(asset("v4.0.1", url("v4.0.1"), digest(), 0));
        assertNull(asset("v4.0.1", url("v4.0.1"), digest(), ReleaseAsset.MAX_BYTES + 1));
        assertNull(asset("v3.5", url("v3.5"), digest(), bytes.length));
        assertNull(asset("v4.1000.0", url("v4.1000.0"), digest(), bytes.length));
        assertNull(asset("v2101.0.0", url("v2101.0.0"), digest(), bytes.length));
        assertNull(ReleaseAsset.parse("v4.0.1", "WebOBS-4.0.1-android-SELF-SIGNED.apk", url("v4.0.1"), digest(), bytes.length, "new"));
    }
    @Test public void writesOnlyCompleteMatchingBytes() throws Exception {
        File directory = Files.createTempDirectory("webobs-apk-integrity-").toFile(), output = new File(directory, "update.apk");
        try {
            ReleaseAsset valid = asset("v4.0.1", url("v4.0.1"), digest(), bytes.length);
            ApkIntegrity.copy(new ByteArrayInputStream(bytes), output, valid);
            assertArrayEquals(bytes, Files.readAllBytes(output.toPath())); ApkIntegrity.verify(output, valid);
            byte[] changed = bytes.clone(); changed[0] ^= 1;
            for (byte[] bad : List.of(changed, java.util.Arrays.copyOf(bytes, bytes.length - 1), java.util.Arrays.copyOf(bytes, bytes.length + 1))) {
                assertThrows(ApkIntegrity.Rejected.class, () -> ApkIntegrity.copy(new ByteArrayInputStream(bad), output, valid));
                assertFalse(output.exists());
            }
        } finally { Files.deleteIfExists(output.toPath()); Files.delete(directory.toPath()); }
    }
    @Test public void incompleteFeedKeepsManualLinkWithoutAutomaticDownload() throws Exception {
        ReleaseAsset valid = asset("v4.0.1", url("v4.0.1"), digest(), bytes.length);
        String name = "WebOBS-4.0.1-android-SELF-SIGNED.apk";
        ReleaseOffer.Candidate candidate = new ReleaseOffer.Candidate("v4.0.1", false, false, List.of(name), "", List.of(valid));
        assertSame(valid, ReleaseOffer.select("4.0.0", List.of(candidate)).asset);
        ReleaseOffer manual = ReleaseOffer.select("4.0.0", List.of(new ReleaseOffer.Candidate("v4.0.1", false, false, List.of(name), "")));
        assertTrue(manual.available); assertNull(manual.asset); assertTrue(manual.message.contains("摘要"));
        assertNull(ReleaseOffer.select("4.0.1", List.of(candidate)).asset);
    }
}
