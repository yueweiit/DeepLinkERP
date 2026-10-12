package com.yuewei.plm.module.operationlog.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.fasterxml.jackson.databind.node.TextNode;
import java.util.ArrayList;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;

/** One write/read policy, including legacy logs. Never fall back to unsafe raw details. */
public final class OperationLogDetails {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final String REDACTED = "[REDACTED]";
    private static final Set<String> SECRET_KEYS = Set.of(
        "password", "passwordhash", "pwd", "passwd", "secret", "clientsecret", "appsecret",
        "token", "accesstoken", "refreshtoken", "idtoken", "sessiontoken", "authtoken",
        "authorization", "apikey", "apisecret", "cookie", "setcookie", "privatekey",
        "credential", "credentials", "jwt", "sessionid", "skey");
    private static final Pattern BEARER = Pattern.compile("(?i)\\bBearer\\s+[^\\s\"'<>;,]+");
    private static final Pattern SECRET_PARAMETER = Pattern.compile(
        "(?i)((?:[?&]|\\b)(?:password|passwd|pwd|authorization|access_token|refresh_token|token|secret|client_secret|api_secret|api_key|skey)\\s*[=:]\\s*)[^&#\\s]+");

    private OperationLogDetails() {}

    public static String sanitize(String raw) {
        if (raw == null || raw.isBlank()) return null;
        try {
            JsonNode value = JSON.readTree(raw);
            if (value == null) return null;
            return JSON.writeValueAsString(clean(value));
        } catch (Exception malformed) {
            return "{\"redactionNotice\":\"非结构化日志详情已隐藏\"}";
        }
    }

    private static JsonNode clean(JsonNode value) {
        if (value.isObject()) {
            ObjectNode object = (ObjectNode) value;
            var fields = new ArrayList<String>();
            object.fieldNames().forEachRemaining(fields::add);
            for (String field : fields) {
                String key = field.toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9]", "");
                if ("passwordchanged".equals(key)) {
                    if (!object.get(field).isBoolean()) object.put(field, REDACTED);
                } else if (SECRET_KEYS.contains(key) || key.endsWith("password") || key.endsWith("passwordhash")
                        || key.endsWith("secret") || key.endsWith("token") || key.endsWith("apikey")
                        || key.endsWith("privatekey")) {
                    object.put(field, REDACTED);
                } else {
                    object.set(field, clean(object.get(field)));
                }
            }
        } else if (value.isArray()) {
            for (int index = 0; index < value.size(); index++)
                ((com.fasterxml.jackson.databind.node.ArrayNode) value).set(index, clean(value.get(index)));
        } else if (value.isTextual()) {
            String safe = BEARER.matcher(value.textValue()).replaceAll("Bearer " + REDACTED);
            safe = SECRET_PARAMETER.matcher(safe).replaceAll("$1" + REDACTED);
            return TextNode.valueOf(safe);
        }
        return value;
    }
}
