package io.github.misery522.yijing.host;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** 小型有界 JSON 编解码器：拒绝重复字段、非 JSON 数字及过深数据，不包含日志。 */
public final class StrictJson {
    public static final int MAX_CHARS = 524288;
    private final String source;
    private int position;
    private int nodes;

    private StrictJson(String source) {
        if (source == null || source.length() > MAX_CHARS) throw invalid();
        this.source = source;
    }

    public static Object parse(String source) {
        StrictJson parser = new StrictJson(source);
        Object result = parser.value(0);
        parser.space();
        if (parser.position != source.length()) throw invalid();
        return result;
    }

    public static String stringify(Object value) {
        StringBuilder result = new StringBuilder();
        encode(value, result, 0, new int[] {0});
        return result.toString();
    }

    private static IllegalArgumentException invalid() {
        return new IllegalArgumentException("INVALID_JSON");
    }

    private void space() {
        while (position < source.length() && " \t\r\n".indexOf(source.charAt(position)) >= 0) position++;
    }

    private boolean take(char value) {
        space();
        if (position < source.length() && source.charAt(position) == value) { position++; return true; }
        return false;
    }

    private Object value(int depth) {
        if (depth > 16 || ++nodes > 20000) throw invalid();
        space();
        if (position >= source.length()) throw invalid();
        char next = source.charAt(position);
        if (next == '"') return string();
        if (take('{')) {
            Map<String, Object> result = new LinkedHashMap<>();
            if (take('}')) return result;
            do {
                space();
                if (position >= source.length() || source.charAt(position) != '"') throw invalid();
                String key = string();
                if (result.containsKey(key) || !take(':')) throw invalid();
                result.put(key, value(depth + 1));
                if (take('}')) return result;
            } while (take(','));
            throw invalid();
        }
        if (take('[')) {
            List<Object> result = new ArrayList<>();
            if (take(']')) return result;
            do {
                result.add(value(depth + 1));
                if (take(']')) return result;
            } while (take(','));
            throw invalid();
        }
        for (String literal : new String[] {"true", "false", "null"}) {
            if (source.startsWith(literal, position)) {
                position += literal.length();
                return literal.equals("null") ? null : Boolean.valueOf(literal);
            }
        }
        int start = position;
        while (position < source.length() && "-+0123456789.eE".indexOf(source.charAt(position)) >= 0) position++;
        String number = source.substring(start, position);
        if (!number.matches("-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")) throw invalid();
        try {
            if (number.indexOf('.') < 0 && number.indexOf('e') < 0 && number.indexOf('E') < 0) {
                long parsed = Long.parseLong(number);
                if (parsed < -9007199254740991L || parsed > 9007199254740991L) throw invalid();
                return parsed;
            }
            double parsed = Double.parseDouble(number);
            if (!Double.isFinite(parsed) || Math.abs(parsed) > 9007199254740991L) throw invalid();
            return parsed;
        } catch (NumberFormatException error) { throw invalid(); }
    }

    private String string() {
        if (source.charAt(position++) != '"') throw invalid();
        StringBuilder result = new StringBuilder();
        while (position < source.length()) {
            char character = source.charAt(position++);
            if (character == '"') { validateUnicode(result.toString()); return result.toString(); }
            if (character < 32) throw invalid();
            if (character == '\\') {
                if (position >= source.length()) throw invalid();
                char escaped = source.charAt(position++);
                String escapes = "\"\\/bfnrt";
                int index = escapes.indexOf(escaped);
                if (index >= 0) character = "\"\\/\b\f\n\r\t".charAt(index);
                else if (escaped == 'u' && position + 4 <= source.length()) {
                    String hex = source.substring(position, position + 4);
                    if (!hex.matches("[0-9a-fA-F]{4}")) throw invalid();
                    character = (char) Integer.parseInt(hex, 16);
                    position += 4;
                } else throw invalid();
            }
            result.append(character);
        }
        throw invalid();
    }

    private static void validateUnicode(String value) {
        for (int i = 0; i < value.length(); i++) {
            char character = value.charAt(i);
            if (Character.isHighSurrogate(character)) {
                if (++i >= value.length() || !Character.isLowSurrogate(value.charAt(i))) throw invalid();
            } else if (Character.isLowSurrogate(character)) throw invalid();
        }
    }

    private static void quote(String value, StringBuilder result) {
        validateUnicode(value);
        result.append('"');
        for (int i = 0; i < value.length(); i++) {
            char character = value.charAt(i);
            int index = "\"\\\b\f\n\r\t".indexOf(character);
            if (index >= 0) result.append('\\').append("\"\\bfnrt".charAt(index));
            else if (character < 32) result.append(String.format(java.util.Locale.ROOT, "\\u%04x", (int) character));
            else result.append(character);
        }
        result.append('"');
    }

    private static void encode(Object value, StringBuilder result, int depth, int[] nodes) {
        if (depth > 16 || ++nodes[0] > 20000 || result.length() > MAX_CHARS) throw invalid();
        if (value == null) result.append("null");
        else if (value instanceof String) quote((String) value, result);
        else if (value instanceof Boolean) result.append(value);
        else if (value instanceof Number) {
            double number = ((Number) value).doubleValue();
            if (!Double.isFinite(number) || Math.abs(number) > 9007199254740991L) throw invalid();
            String encoded = value.toString();
            if (!encoded.matches("-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")) throw invalid();
            result.append(encoded);
        } else if (value instanceof Map) {
            result.append('{'); boolean first = true;
            for (Map.Entry<?, ?> entry : ((Map<?, ?>) value).entrySet()) {
                if (!(entry.getKey() instanceof String)) throw invalid();
                if (!first) result.append(','); first = false;
                quote((String) entry.getKey(), result); result.append(':');
                encode(entry.getValue(), result, depth + 1, nodes);
            }
            result.append('}');
        } else if (value instanceof List) {
            result.append('['); boolean first = true;
            for (Object child : (List<?>) value) {
                if (!first) result.append(','); first = false;
                encode(child, result, depth + 1, nodes);
            }
            result.append(']');
        } else throw invalid();
        if (result.length() > MAX_CHARS) throw invalid();
    }
}
