package io.github.liaoyk001.webobs.android;

import android.app.DownloadManager;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.os.Environment;
import android.os.ParcelFileDescriptor;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;

/** Platform boundary: DownloadManager owns network retry/continuation and its notifications. */
interface UpdateDownloads {
    final class Status {
        final int phase, reason;
        final long received, total;
        Status(int phase, int reason, long received, long total) { this.phase = phase; this.reason = reason; this.received = received; this.total = total; }
    }
    long start(ReleaseAsset asset, boolean wifiOnly) throws IOException;
    long recover(ReleaseAsset asset);
    Status status(long id);
    InputStream open(long id) throws IOException;
    void remove(long id);

    final class SystemDownloads implements UpdateDownloads {
        private final Context context;
        private final DownloadManager manager;
        SystemDownloads(Context context) { this.context = context; manager = context.getSystemService(DownloadManager.class); }
        private File destination() { File directory = context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS); return directory == null ? null : new File(directory, "webobs-updates/update.apk"); }
        @Override public long start(ReleaseAsset asset, boolean wifiOnly) throws IOException {
            File file = destination();
            if (manager == null || file == null) throw new IOException("Download storage unavailable");
            if (!file.getParentFile().isDirectory() && !file.getParentFile().mkdirs()) throw new IOException("Download storage unavailable");
            if (file.exists() && !file.delete()) throw new IOException("Old download cannot be removed");
            DownloadManager.Request request = new DownloadManager.Request(Uri.parse(asset.url));
            request.setTitle("WebOBS " + asset.version + " 更新").setDescription("下载后须通过客户端校验，再由你确认安装")
                    .setDestinationUri(Uri.fromFile(file)).setMimeType("application/vnd.android.package-archive")
                    .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE)
                    .setAllowedOverMetered(!wifiOnly).setAllowedOverRoaming(false);
            if (wifiOnly) request.setAllowedNetworkTypes(DownloadManager.Request.NETWORK_WIFI);
            return manager.enqueue(request);
        }
        @Override public long recover(ReleaseAsset asset) {
            File file = destination();
            if (manager == null || file == null) return -1;
            long found = -1;
            try (Cursor cursor = manager.query(new DownloadManager.Query())) {
                if (cursor != null) while (cursor.moveToNext()) {
                    if (asset.url.equals(cursor.getString(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_URI)))
                            && Uri.fromFile(file).toString().equals(cursor.getString(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_LOCAL_URI)))) {
                        found = Math.max(found, cursor.getLong(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_ID)));
                    }
                }
            }
            return found;
        }
        @Override public Status status(long id) {
            try (Cursor cursor = manager.query(new DownloadManager.Query().setFilterById(id))) {
                if (cursor == null || !cursor.moveToFirst()) return null;
                return new Status(cursor.getInt(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS)),
                        cursor.getInt(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_REASON)),
                        cursor.getLong(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_BYTES_DOWNLOADED_SO_FAR)),
                        cursor.getLong(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_TOTAL_SIZE_BYTES)));
            }
        }
        @Override public InputStream open(long id) throws IOException { return new ParcelFileDescriptor.AutoCloseInputStream(manager.openDownloadedFile(id)); }
        @Override public void remove(long id) { if (id >= 0 && manager != null) manager.remove(id); }
    }
}
