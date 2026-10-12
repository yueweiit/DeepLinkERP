package com.yuewei.plm.module.integration.dingtalk.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.module.integration.dingtalk.config.DingTalkIntegrationProperties;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.web.client.RestTemplate;

@Service
@RequiredArgsConstructor
public class DingTalkOutboundApprovalClient {
    private final DingTalkIntegrationProperties properties;
    private final ObjectMapper objectMapper;
    private final RestTemplate restTemplate = new RestTemplate();

    public DingTalkOutboundResult startShipMoldProcess(Map<String, Object> payload) {
        return postOrDryRun(payload, null);
    }

    public DingTalkOutboundResult executeWorkflowTask(Map<String, Object> payload) {
        return postOrDryRun(payload, "workflow-execute");
    }

    public String lookupWorkflowTask(Map<String, Object> payload) {
        if (!StringUtils.hasText(properties.getOutboundEndpoint())) {
            return null;
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> response = restTemplate.postForObject(properties.getOutboundEndpoint(), payload, Map.class);
        Map<String, Object> body = data(response);
        String taskId = text(body, "taskId", "approvalTaskId", "task_id", "id");
        return StringUtils.hasText(taskId) ? taskId : text(response, "taskId", "approvalTaskId", "task_id", "id");
    }

    public DingTalkOutboundResult sendCompletionNotice(Map<String, Object> payload) {
        return postOrDryRun(payload, "completion-notice");
    }

    private DingTalkOutboundResult postOrDryRun(Map<String, Object> payload, String action) {
        if (!StringUtils.hasText(properties.getOutboundEndpoint())) {
            return new DingTalkOutboundResult(
                dryRunInstanceId(payload, action),
                null,
                "dry_run",
                toJson(payload)
            );
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> response = restTemplate.postForObject(properties.getOutboundEndpoint(), payload, Map.class);
        Map<String, Object> body = data(response);
        return new DingTalkOutboundResult(
            firstText(body, response, "instanceId", "processInstanceId", "approvalInstanceId"),
            firstText(body, response, "url", "externalUrl", "formUrl"),
            firstText(body, response, "status", "externalStatus"),
            toJson(response)
        );
    }

    private String dryRunInstanceId(Map<String, Object> payload, String action) {
        String suffix = payload.get("projectId") + "-" + payload.get("nodeKey");
        return StringUtils.hasText(action) ? "dry-run-" + action + "-" + suffix : "dry-run-" + suffix;
    }

    private String text(Map<String, Object> value, String... keys) {
        if (value == null) return null;
        for (String key : keys) {
            Object item = value.get(key);
            if (item != null && StringUtils.hasText(String.valueOf(item))) {
                return String.valueOf(item);
            }
        }
        return null;
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> data(Map<String, Object> response) {
        if (response == null) {
            return null;
        }
        Object data = response.get("data");
        return data instanceof Map<?, ?> ? (Map<String, Object>) data : response;
    }

    private String firstText(Map<String, Object> primary, Map<String, Object> fallback, String... keys) {
        String value = text(primary, keys);
        return StringUtils.hasText(value) ? value : text(fallback, keys);
    }

    private String toJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception ignored) {
            return null;
        }
    }

    public record DingTalkOutboundResult(String externalInstanceId, String externalUrl, String externalStatus, String rawPayloadJson) {}
}
