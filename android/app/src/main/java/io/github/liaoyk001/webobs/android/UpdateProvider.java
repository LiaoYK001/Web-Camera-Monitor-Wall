package io.github.liaoyk001.webobs.android;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.File;
import java.io.FileNotFoundException;

/** Only one read-only, verified APK may be granted to the system installer. */
public final class UpdateProvider extends ContentProvider {
    @Override public boolean onCreate() { return true; }
    private File file(Uri uri) throws FileNotFoundException {
        if (getContext() == null) throw new FileNotFoundException("No update context");
        android.content.SharedPreferences store = getContext().getSharedPreferences(AndroidUpdates.STORE, 0);
        String digest = store.getString("sha256", "");
        Uri expected = Uri.parse("content://" + getContext().getPackageName() + ".updates/apk/" + digest);
        File file = AndroidUpdates.readyFile(getContext());
        if (!digest.matches("[a-f0-9]{64}") || !expected.equals(uri) || !store.getBoolean("ready", false) || !file.isFile()) throw new FileNotFoundException("No verified update");
        return file;
    }
    @Override public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        if (!"r".equals(mode)) throw new FileNotFoundException("Update is read-only");
        return ParcelFileDescriptor.open(file(uri), ParcelFileDescriptor.MODE_READ_ONLY);
    }
    @Override public Cursor query(Uri uri, String[] projection, String selection, String[] args, String order) {
        try {
            File file = file(uri); MatrixCursor result = new MatrixCursor(new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE});
            result.addRow(new Object[]{"WebOBS-update.apk", file.length()}); return result;
        } catch (FileNotFoundException error) { return new MatrixCursor(new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE}); }
    }
    @Override public String getType(Uri uri) { try { file(uri); return "application/vnd.android.package-archive"; } catch (FileNotFoundException error) { return null; } }
    @Override public Uri insert(Uri uri, ContentValues values) { throw new UnsupportedOperationException("Read-only update"); }
    @Override public int delete(Uri uri, String selection, String[] args) { throw new UnsupportedOperationException("Read-only update"); }
    @Override public int update(Uri uri, ContentValues values, String selection, String[] args) { throw new UnsupportedOperationException("Read-only update"); }
}
