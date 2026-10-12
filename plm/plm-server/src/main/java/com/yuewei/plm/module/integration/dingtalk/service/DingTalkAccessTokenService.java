package com.yuewei.plm.module.integration.dingtalk.service;

import com.yuewei.plm.module.integration.dingtalk.config.DingTalkIntegrationProperties;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.web.client.RestTemplate;

@Service
@RequiredArgsConstructor
public class DingTalkAccessTokenService {
    private static final String ACCESS_TOKEN_URL = "https://api.dingtalk.com/v1.0/oauth2/accessToken";
    private static final long EXPIRE_SKEW_SECONDS = 300L;

    private final DingTalkIntegrationProperties properties;
    private final RestTemplate restTemplate = new RestTemplate();

    private String cachedAccessToken;
    private Instant expiresAt = Instant.EPOCH;

    public synchronized String getAccessToken() {
        if (StringUtils.hasText(cachedAccessToken) && Instant.now().isBefore(expiresAt)) {
            return cachedAccessToken;
        }
        if (!StringUtils.hasText(properties.getAppKey()) || !StringUtils.hasText(properties.getAppSecret())) {
            throw new DingTalkOfficialApprovalException(
                "DINGTALK_CREDENTIALS_REQUIRED",
                "DingTalk appKey/appSecret is required"
            );
        }

        Map<String, Object> request = new LinkedHashMap<>();
        request.put("appKey", properties.getAppKey());
        request.put("appSecret", properties.getAppSecret());
        @SuppressWarnings("unchecked")
        Map<String, Object> response = restTemplate.postForObject(ACCESS_TOKEN_URL, request, Map.class);
        String accessToken = text(response, "accessToken", "access_token");
        if (!StringUtils.hasText(accessToken)) {
            throw new DingTalkOfficialApprovalException(
                "DINGTALK_ACCESS_TOKEN_FAILED",
                "DingTalk access token response does not contain accessToken"
            );
        }
        cachedAccessToken = accessToken;
        expiresAt = Instant.now().plusSeconds(Math.max(60L, number(response, "expireIn", "expires_in") - EXPIRE_SKEW_SECONDS));
        return cachedAccessToken;
    }

    private String text(Map<String, Object> value, String... keys) {
        if (value == null) {
            return null;
        }
        for (String key : keys) {
            Object item = value.get(key);
            if (item != null && StringUtils.hasText(String.valueOf(item))) {
                return String.valueOf(item);
            }
        }
        return null;
    }

    private long number(Map<String, Object> value, String... keys) {
        String text = text(value, keys);
        if (!StringUtils.hasText(text)) {
            return 7200L;
        }
        try {
            return Long.parseLong(text);
        } catch (NumberFormatException ignored) {
            return 7200L;
        }
    }
}
