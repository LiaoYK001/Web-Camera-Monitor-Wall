package io.github.liaoyk001.webobs.android;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Product tags vA.B / vA.B.C map to numeric APK versions A.B.0 / A.B.C. */
public final class ReleaseVersion implements Comparable<ReleaseVersion> {
    private static final String NUMBER = "(0|[1-9][0-9]{0,8})";
    private static final Pattern TAG = Pattern.compile("v" + NUMBER + "\\." + NUMBER + "(?:\\." + NUMBER + ")?");
    private static final Pattern INSTALLED = Pattern.compile(NUMBER + "\\." + NUMBER + "\\." + NUMBER + "(-dev\\.[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?");
    public final int major, minor, patch;
    public final boolean development;

    private ReleaseVersion(int major, int minor, int patch, boolean development) {
        this.major = major; this.minor = minor; this.patch = patch; this.development = development;
    }
    public static ReleaseVersion tag(String value) { return parse(value, TAG, true); }
    public static ReleaseVersion installed(String value) { return parse(value, INSTALLED, false); }
    private static ReleaseVersion parse(String value, Pattern pattern, boolean tag) {
        if (value == null) return null;
        Matcher match = pattern.matcher(value);
        if (!match.matches()) return null;
        return new ReleaseVersion(Integer.parseInt(match.group(1)), Integer.parseInt(match.group(2)),
                match.group(3) == null ? 0 : Integer.parseInt(match.group(3)), !tag && match.group(4) != null);
    }
    @Override public String toString() { return major + "." + minor + "." + patch; }
    @Override public int compareTo(ReleaseVersion other) {
        int order = Integer.compare(major, other.major);
        if (order == 0) order = Integer.compare(minor, other.minor);
        if (order == 0) order = Integer.compare(patch, other.patch);
        if (order == 0) order = Boolean.compare(other.development, development);
        return order;
    }
    public String updateLabel(ReleaseVersion current) {
        if (major != current.major) return "大版本更新";
        if (minor != current.minor) return "功能更新";
        return patch != current.patch ? "修复补丁" : "正式版本";
    }
}
