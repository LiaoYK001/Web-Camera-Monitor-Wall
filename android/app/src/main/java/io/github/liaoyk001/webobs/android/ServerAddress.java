package io.github.liaoyk001.webobs.android;

import java.net.URI;
import java.util.Locale;

/** Only a product origin is configured; credentials and camera URLs stay in WebUI. */
public final class ServerAddress {
    private ServerAddress() {}

    public static String normalize(String input) {
        if (input == null || input.length() > 2048) throw new IllegalArgumentException("地址过长或为空");
        try {
            URI uri = new URI(input.trim());
            String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase(Locale.ROOT);
            String host = uri.getHost();
            if (host == null || uri.getRawUserInfo() != null || uri.getRawQuery() != null || uri.getRawFragment() != null
                || !(uri.getRawPath() == null || uri.getRawPath().isEmpty() || uri.getRawPath().equals("/"))
                || uri.getPort() == 0 || uri.getPort() > 65535) throw new IllegalArgumentException();
            host = host.toLowerCase(Locale.ROOT);
            boolean loopback = host.equals("localhost") || host.equals("127.0.0.1") || host.equals("::1") || host.equals("[::1]");
            if (!scheme.equals("https") && !(scheme.equals("http") && loopback)) throw new IllegalArgumentException();
            int port = uri.getPort();
            if ((scheme.equals("https") && port == 443) || (scheme.equals("http") && port == 80)) port = -1;
            return new URI(scheme, null, host, port, "/", null, null).toASCIIString();
        } catch (Exception error) {
            throw new IllegalArgumentException("请输入 HTTPS 服务器地址，不含账号、路径或查询参数；ADB 本机测试可使用 http://127.0.0.1:端口。");
        }
    }

    public static boolean sameOrigin(String candidate, String origin) {
        try {
            URI uri = new URI(candidate);
            if (uri.getRawUserInfo() != null || uri.getHost() == null) return false;
            return normalize(new URI(uri.getScheme(), null, uri.getHost(), uri.getPort(), "/", null, null).toASCIIString()).equals(origin);
        } catch (Exception error) { return false; }
    }
}
