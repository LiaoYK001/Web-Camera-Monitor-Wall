package io.github.liaoyk001.webobs.android;

import android.content.Context;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import java.io.File;
import java.io.IOException;
import java.util.Arrays;

/** Compare with the actual installed package, not a feed-provided publisher identity. */
public final class ApkVerifier {
    private ApkVerifier() {}
    public static void verify(Context context, File apk, ReleaseAsset asset) throws IOException {
        ApkIntegrity.verify(apk, asset);
        verifyIdentity(context, apk, asset);
    }
    static void verifyIdentity(Context context, File apk, ReleaseAsset asset) throws IOException {
        PackageManager manager = context.getPackageManager();
        PackageInfo target = manager.getPackageArchiveInfo(apk.getAbsolutePath(), PackageManager.GET_SIGNING_CERTIFICATES);
        PackageInfo installed;
        try { installed = manager.getPackageInfo(context.getPackageName(), PackageManager.GET_SIGNING_CERTIFICATES); }
        catch (PackageManager.NameNotFoundException error) { throw new IOException("无法读取当前安装版本，请重启客户端后重试。", error); }
        if (target == null || target.applicationInfo == null || !context.getPackageName().equals(target.packageName)
                || !asset.version.equals(target.versionName) || target.getLongVersionCode() != asset.versionCode
                || target.getLongVersionCode() <= installed.getLongVersionCode()
                || (target.applicationInfo.flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0) {
            throw new ApkIntegrity.Rejected("APK 包名、版本或正式构建标记不匹配，已拒绝安装。当前客户端可继续使用。");
        }
        if (target.signingInfo == null || installed.signingInfo == null
                || !sameSigners(target.signingInfo.getApkContentsSigners(), installed.signingInfo.getApkContentsSigners())) {
            throw new ApkIntegrity.Rejected("APK 签名与当前安装不同，无法保留数据覆盖更新。请联系维护者使用原密钥构建，不要卸载现有客户端。");
        }
    }
    private static boolean sameSigners(Signature[] target, Signature[] installed) {
        if (target == null || installed == null || target.length == 0 || target.length != installed.length) return false;
        for (Signature signer : target) if (Arrays.stream(installed).noneMatch(signer::equals)) return false;
        return true;
    }
}
