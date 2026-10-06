package io.github.liaoyk001.webobs.android;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;

/** Limit both feed allocation and elapsed time, including slowly arriving responses. */
final class ReleaseBody {
    private ReleaseBody() {}
    static byte[] read(InputStream input, long deadlineNanos) throws IOException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream(); byte[] buffer = new byte[8192];
        while (true) {
            if (System.nanoTime() - deadlineNanos >= 0) throw new IOException("Release check deadline exceeded");
            int count = input.read(buffer);
            if (System.nanoTime() - deadlineNanos >= 0) throw new IOException("Release check deadline exceeded");
            if (count == -1) return bytes.toByteArray();
            if (bytes.size() + count > 512 * 1024) throw new IOException("Release response too large");
            bytes.write(buffer, 0, count);
        }
    }
}
