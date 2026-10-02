package io.github.liaoyk001.webobs.android;
import org.junit.Test;
import static org.junit.Assert.*;

public class ServerAddressTest {
    @Test public void normalizesOriginsAndSupportsAdbLoopback() {
        assertEquals("https://example.com/", ServerAddress.normalize(" HTTPS://Example.COM:443/ "));
        assertEquals("https://192.168.1.20:18443/", ServerAddress.normalize("https://192.168.1.20:18443"));
        assertEquals("http://127.0.0.1:18080/", ServerAddress.normalize("http://127.0.0.1:18080"));
        assertEquals("http://[::1]:18080/", ServerAddress.normalize("http://[::1]:18080"));
    }
    @Test public void rejectsCredentialsPathsInvalidPortsAndCleartextLan() {
        for (String value : new String[]{"https://user:secret@example.com", "https://example.com/api", "https://example.com/?token=private", "https://example.com/#private", "http://192.168.1.20", "file:///data/local/tmp/private", "javascript:alert(1)", "https://example.com:0", "https://example.com:99999", "https://example.com:-2", "https://example.com\\evil", "http://127.0.0.1.evil.example"}) {
            try { ServerAddress.normalize(value); fail("Accepted unsafe origin"); } catch (IllegalArgumentException expected) { }
        }
    }
    @Test public void navigationCannotLeaveTheSelectedOriginOrChangeItsCredentials() {
        String origin = "https://example.com:18443/";
        assertTrue(ServerAddress.sameOrigin("https://example.com:18443/#projector?scene=main", origin));
        assertTrue(ServerAddress.sameOrigin("https://example.com:18443/api/v1/go2rtc/config.html", origin));
        assertFalse(ServerAddress.sameOrigin("https://example.com.evil:18443/", origin));
        assertFalse(ServerAddress.sameOrigin("https://user:secret@example.com:18443/", origin));
        assertFalse(ServerAddress.sameOrigin("http://example.com:18443/", origin));
        assertFalse(ServerAddress.sameOrigin("https://example.com/", origin));
    }
}
