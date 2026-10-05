package io.github.liaoyk001.webobs.android;
import org.junit.Test;
import static org.junit.Assert.*;
import java.io.ByteArrayInputStream;
import java.io.IOException;

public class ReleaseBodyTest {
    @Test public void acceptsBoundedFeedRejectsOversizedOrExpiredReads() throws Exception {
        byte[] body = "[]".getBytes(java.nio.charset.StandardCharsets.UTF_8);
        assertArrayEquals(body, ReleaseBody.read(new ByteArrayInputStream(body), System.nanoTime() + 1000000000L));
        assertThrows(IOException.class, () -> ReleaseBody.read(new ByteArrayInputStream(new byte[512 * 1024 + 1]), System.nanoTime() + 1000000000L));
        assertThrows(IOException.class, () -> ReleaseBody.read(new ByteArrayInputStream(body), System.nanoTime() - 1));
        ByteArrayInputStream slow = new ByteArrayInputStream(body) {
            @Override public int read(byte[] buffer, int offset, int length) {
                try { Thread.sleep(60); } catch (InterruptedException error) { Thread.currentThread().interrupt(); }
                return super.read(buffer, offset, length);
            }
        };
        assertThrows(IOException.class, () -> ReleaseBody.read(slow, System.nanoTime() + 10000000L));
    }
}
