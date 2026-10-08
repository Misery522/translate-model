package io.github.misery522.yijing.host;

import java.util.Map;

/** 实际 JVM 测试，不使用 Android stub，也不请求模型或公网。 */
public final class HostTests {
    private static int count;
    private static void check(boolean condition) {
        if (!condition) throw new AssertionError("HOST_TEST_FAILED"); count++;
    }
    private static void invalid(String input) {
        try { StrictJson.parse(input); throw new AssertionError("INVALID_JSON_ACCEPTED"); }
        catch (IllegalArgumentException expected) { count++; }
    }
    public static void main(String[] arguments) {
        for (String valid : new String[] {"{}", "[]", "true", "false", "null", "0", "-1", "1.5e+2", "\"中文😀\\n\"", "{\"a\":[null,true,7]}"}) {
            Object value = StrictJson.parse(valid);
            check(StrictJson.stringify(value).equals(StrictJson.stringify(StrictJson.parse(StrictJson.stringify(value)))));
        }
        for (String invalid : new String[] {"{\"a\":1,\"a\":2}", "{\"a\":0,\"\\u0061\":2}", "[1,]", "{\"a\":1,}", "+1", "01", "NaN", "Infinity", "1e999", "9007199254740992", "{}{}", "\"\\ud800\"", "\"\\q\"", "\"\n\"", "[", "[true false]"}) invalid(invalid);
        invalid("[".repeat(18) + "0" + "]".repeat(18));
        invalid(" ".repeat(StrictJson.MAX_CHARS + 1));
        check(BrowserPolicy.supportedUserAgent("Android; wv Chrome/111.0.0.0 Mobile"));
        check(!BrowserPolicy.supportedUserAgent("HuaweiBrowser/10.0"));
        check(!BrowserPolicy.supportedUserAgent("Android Chrome/110.0.0.0"));
        check(!BrowserPolicy.supportedUserAgent(null));
        check(BrowserPolicy.entry(BrowserPolicy.ENTRY));
        check(BrowserPolicy.entry(BrowserPolicy.ENTRY + "#main-content"));
        check("assets/index-a1.js".equals(BrowserPolicy.asset("https://localhost/app/assets/index-a1.js")));
        for (String address : new String[] {"http://localhost/app/index.html", "https://localhost:443/app/index.html", "https://localhost.evil/app/index.html", "https://user@localhost/app/index.html", "file:///app/index.html", "data:text/html,hi", "javascript:alert(1)", "https://localhost/app/../private", "https://localhost/app/%2e%2e/private", "https://localhost/app/index.html?redirect=evil", "https://localhost/app/sw.js", "https://other.example/app/index.html"}) {
            check(BrowserPolicy.asset(address) == null); check(!BrowserPolicy.entry(address));
        }
        check(((Map<?, ?>) StrictJson.parse("{\"null\":null}")).containsKey("null"));
        java.util.Map<String, Object> limit = new java.util.LinkedHashMap<>();
        limit.put("a", "x".repeat(StrictJson.MAX_CHARS - 8));
        check(StrictJson.stringify(limit).length() == StrictJson.MAX_CHARS);
        Map<?, ?> reply = (Map<?, ?>) StrictJson.parse(BridgeReplies.success("11111111-1111-4111-8111-111111111111", limit));
        check(!reply.containsKey("data") && ((Map<?, ?>) reply.get("error")).get("code").equals("INVALID_RESPONSE"));
        HttpTests.run();
        System.out.println("Host JSON/browser tests passed: " + count);
    }
}
