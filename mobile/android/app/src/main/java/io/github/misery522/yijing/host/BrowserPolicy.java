package io.github.misery522.yijing.host;

import java.net.URI;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** 不依赖 Android 的来源、资源和 WebView 门禁，便于真实 JVM 回归测试。 */
public final class BrowserPolicy {
    public static final String ORIGIN = "https://localhost";
    public static final String ENTRY = ORIGIN + "/app/index.html";
    private static final Pattern CHROMIUM = Pattern.compile("(?:^|\\s)Chrome/([0-9]+)\\.");

    private BrowserPolicy() {}

    public static boolean supportedUserAgent(String agent) {
        if (agent == null || agent.length() > 2048) return false;
        Matcher matcher = CHROMIUM.matcher(agent);
        if (!matcher.find()) return false;
        try { return Integer.parseInt(matcher.group(1)) >= 111; }
        catch (NumberFormatException error) { return false; }
    }

    public static String asset(String address) {
        try {
            URI uri = new URI(address);
            if (!"https".equals(uri.getScheme()) || !"localhost".equals(uri.getRawAuthority())
                || uri.getRawQuery() != null || uri.getRawFragment() != null) return null;
            String path = uri.getRawPath();
            if ("/app/index.html".equals(path)) return "index.html";
            if (path != null && path.matches("/app/assets/[A-Za-z0-9_-]+(?:\\.[A-Za-z0-9_-]+)*\\.(?:js|css|svg|woff2)"))
                return path.substring(5);
            if (path != null && path.matches("/app/notices/[A-Za-z0-9_.-]+\\.txt"))
                return path.substring(5);
        } catch (Exception error) { return null; }
        return null;
    }

    public static boolean entry(String address) {
        return ENTRY.equals(address) || (ENTRY + "#main-content").equals(address);
    }
}
