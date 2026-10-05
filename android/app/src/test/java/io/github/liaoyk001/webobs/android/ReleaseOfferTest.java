package io.github.liaoyk001.webobs.android;

import org.junit.Test;
import java.util.List;
import static org.junit.Assert.*;

public class ReleaseOfferTest {
    private ReleaseOffer.Candidate apk(String tag, String version) {
        return new ReleaseOffer.Candidate(tag, false, false, List.of("WebOBS-" + version + "-android-SELF-SIGNED.apk"), "修复异常恢复 / Fix recovery");
    }
    @Test public void patchesCompareNumericallyAndShowExactReleaseNotes() {
        ReleaseOffer offer = ReleaseOffer.select("4.0.9", List.of(apk("v4.0.10", "4.0.10"), apk("v4.0.2", "4.0.2")));
        assertTrue(offer.available);
        assertTrue(offer.message.contains("修复补丁 4.0.10"));
        assertTrue(offer.message.contains("Fix recovery"));
        assertEquals(ReleaseOffer.REPOSITORY + "/releases/tag/v4.0.10", offer.releaseUrl);
        assertTrue(ReleaseOffer.select("4.0.0", List.of(apk("v4.0.1", "4.0.1"))).available);
        assertTrue(ReleaseOffer.select("4.0.1", List.of(apk("v4.0.2", "4.0.2"))).available);
    }
    @Test public void newerBackendOnlyReleaseDoesNotHideAnAvailableAndroidPatch() {
        ReleaseOffer offer = ReleaseOffer.select("4.0.0", List.of(
                new ReleaseOffer.Candidate("v4.0.2", false, false, List.of("latest.yml"), "Backend only"), apk("v4.0.1", "4.0.1")));
        assertTrue(offer.available);
        assertTrue(offer.releaseUrl.endsWith("/v4.0.1"));
    }
    @Test public void noDowngradesAndLegacyTagsMapToZeroPatch() {
        assertFalse(ReleaseOffer.select("4.0.2", List.of(apk("v4.0.1", "4.0.1"))).available);
        assertFalse(ReleaseOffer.select("4.0.1", List.of(apk("v4.0.1", "4.0.1"))).available);
        assertEquals("4.0.0", ReleaseVersion.tag("v4.0").toString());
        assertTrue(ReleaseOffer.select("4.0.0-dev.android.1", List.of(apk("v4.0", "4.0.0"))).available);
        assertFalse(ReleaseOffer.select("4.0.2-dev.android.1", List.of(apk("v4.0.1", "4.0.1"))).available);
    }
    @Test public void draftPrereleaseWrongAssetAndUnsafeTagAreExcluded() {
        for (ReleaseOffer.Candidate candidate : List.of(
                new ReleaseOffer.Candidate("v4.0.1", true, false, List.of("WebOBS-4.0.1-android-SELF-SIGNED.apk"), ""),
                new ReleaseOffer.Candidate("v4.0.1", false, true, List.of("WebOBS-4.0.1-android-SELF-SIGNED.apk"), ""),
                apk("v4.0.1", "4.0.2"), apk("v4.0.1-dev.1", "4.0.1"), apk("v04.0.1", "04.0.1"), apk("v4.0.1/../../other", "4.0.1"),
                new ReleaseOffer.Candidate("v4.0.1", false, false, List.of("WebOBS-4.0.1-android-DEVELOPMENT.apk"), ""))) {
            assertFalse(ReleaseOffer.select("4.0.0", List.of(candidate)).available);
        }
        assertNull(ReleaseVersion.tag("v4.0.1\n"));
        assertNull(ReleaseVersion.tag("v4.0.1000000000"));
        assertFalse(ReleaseOffer.select("unknown", List.of(apk("v4.0.1", "4.0.1"))).available);
    }
    @Test public void majorAndMinorUpdatesAreDistinctAndNotesAreBounded() {
        assertTrue(ReleaseOffer.select("4.0.9", List.of(apk("v4.1", "4.1.0"))).message.contains("功能更新"));
        assertTrue(ReleaseOffer.select("4.99.99", List.of(apk("v5.0", "5.0.0"))).message.contains("大版本更新"));
        ReleaseOffer.Candidate large = new ReleaseOffer.Candidate("v4.0.1", false, false, List.of("WebOBS-4.0.1-android-SELF-SIGNED.apk"), "x".repeat(10000));
        assertTrue(ReleaseOffer.select("4.0.0", List.of(large)).message.length() < 4500);
    }
}
