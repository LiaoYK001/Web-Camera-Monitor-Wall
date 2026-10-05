package io.github.liaoyk001.webobs.android;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

/** Bounded streaming validation; partially copied/unverified files are never installed. */
public final class ApkIntegrity {
    public static final class Rejected extends IOException {
        Rejected(String message) { super(message); }
    }
    private ApkIntegrity() {}
    public static void copy(InputStream input, File destination, ReleaseAsset asset) throws IOException {
        try (FileOutputStream output = new FileOutputStream(destination)) {
            verify(input, output, asset);
            output.getFD().sync();
        } catch (IOException error) {
            if (destination.exists() && !destination.delete()) throw new IOException("无法移除未校验的更新文件。请重启客户端后重试。", error);
            throw error;
        }
    }
    public static void verify(File file, ReleaseAsset asset) throws IOException {
        if (!file.isFile() || file.length() != asset.size) throw new Rejected("更新文件大小不匹配，请重新下载。");
        try (InputStream input = new FileInputStream(file)) { verify(input, null, asset); }
    }
    private static void verify(InputStream input, FileOutputStream output, ReleaseAsset asset) throws IOException {
        MessageDigest digest;
        try { digest = MessageDigest.getInstance("SHA-256"); } catch (NoSuchAlgorithmException error) { throw new IOException("设备无法校验更新。", error); }
        long size = 0; byte[] buffer = new byte[65536]; int count;
        while ((count = input.read(buffer)) != -1) {
            size += count;
            if (size > asset.size || size > ReleaseAsset.MAX_BYTES) throw new Rejected("更新文件超过声明大小，已拒绝安装。");
            digest.update(buffer, 0, count);
            if (output != null) output.write(buffer, 0, count);
        }
        if (size != asset.size || !MessageDigest.isEqual(digest.digest(), decode(asset.sha256))) throw new Rejected("更新文件不完整或摘要不匹配，请重新下载。");
    }
    private static byte[] decode(String value) {
        byte[] bytes = new byte[32];
        for (int index = 0; index < bytes.length; index++) bytes[index] = (byte) Integer.parseInt(value.substring(index * 2, index * 2 + 2), 16);
        return bytes;
    }
}
