package io.github.misery522.yijing.host;

import java.util.LinkedHashMap;
import java.util.Map;

/** 连同桥接外层一起验证容量；序列化失败只返回小型固定错误。 */
public final class BridgeReplies {
    private BridgeReplies() {}
    public static String success(String id, Map<String, Object> result) {
        Map<String, Object> output = new LinkedHashMap<>(); output.put("id", id); output.put("data", result);
        try { return StrictJson.stringify(output); }
        catch (IllegalArgumentException failure) { return error(id, "INVALID_RESPONSE", 0, false); }
    }
    public static String error(String id, String code, int status, boolean retryable) {
        Map<String, Object> problem = new LinkedHashMap<>(); problem.put("code", code); problem.put("retryable", retryable);
        if (status >= 400 && status <= 599) problem.put("status", status);
        Map<String, Object> output = new LinkedHashMap<>(); output.put("id", id); output.put("error", problem);
        return StrictJson.stringify(output);
    }
}
