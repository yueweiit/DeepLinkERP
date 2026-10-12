package com.yuewei.plm.module.integration.dingtalk.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.util.StringUtils;
import org.springframework.web.client.RestTemplate;

@Service
@RequiredArgsConstructor
public class DingTalkOfficialApprovalClient {
    private static final String INSTANCE_GET_URL = "https://oapi.dingtalk.com/topapi/processinstance/get?access_token=";
    private static final String INSTANCE_EXECUTE_URL = "https://api.dingtalk.com/v1.0/workflow/processInstances/execute";
    private static final String STATUS_RUNNING = "RUNNING";

    private final DingTalkAccessTokenService accessTokenService;
    private final ObjectMapper objectMapper;
    private final RestTemplate restTemplate = new RestTemplate();

    public TaskLookupResult lookupRunningTaskId(String processInstanceId, String actionerUserId) {
        if (!StringUtils.hasText(processInstanceId)) {
            throw new DingTalkOfficialApprovalException(
                "DINGTALK_APPROVAL_INSTANCE_REQUIRED",
                "approvalInstanceId is required"
            );
        }
        String accessToken = accessTokenService.getAccessToken();
        Map<String, Object> request = Map.of("process_instance_id", processInstanceId);
        @SuppressWarnings("unchecked")
        Map<String, Object> response = restTemplate.postForObject(INSTANCE_GET_URL + accessToken, request, Map.class);
        ensureSuccess(response, "DINGTALK_PROCESS_INSTANCE_QUERY_FAILED", "query DingTalk process instance failed");
        return extractRunningTaskId(response, actionerUserId);
    }

    public OfficialAgreeResult agreeTask(
        String processInstanceId,
        String taskId,
        String actionerUserId,
        String remark
    ) {
        if (!StringUtils.hasText(processInstanceId)) {
            throw new DingTalkOfficialApprovalException(
                "DINGTALK_APPROVAL_INSTANCE_REQUIRED",
                "approvalInstanceId is required"
            );
        }
        if (!StringUtils.hasText(taskId)) {
            throw new DingTalkOfficialApprovalException("DINGTALK_TASK_ID_REQUIRED", "taskId is required");
        }
        if (!StringUtils.hasText(actionerUserId)) {
            throw new DingTalkOfficialApprovalException(
                "DINGTALK_ACTIONER_USER_ID_REQUIRED",
                "actionerUserId is required"
            );
        }

        String accessToken = accessTokenService.getAccessToken();
        Map<String, Object> request = new LinkedHashMap<>();
        request.put("processInstanceId", processInstanceId);
        request.put("taskId", taskId);
        request.put("actionerUserId", actionerUserId);
        request.put("result", "agree");
        request.put("remark", StringUtils.hasText(remark) ? remark : "PLM completed, auto agree");

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.set("x-acs-dingtalk-access-token", accessToken);

        @SuppressWarnings("unchecked")
        Map<String, Object> response = restTemplate.postForObject(
            INSTANCE_EXECUTE_URL,
            new HttpEntity<>(request, headers),
            Map.class
        );
        ensureSuccess(response, "DINGTALK_AGREE_FAILED", "agree DingTalk process task failed");
        return new OfficialAgreeResult(taskId, toJson(response));
    }

    public TaskLookupResult extractRunningTaskId(Map<String, Object> response, String actionerUserId) {
        List<Map<String, Object>> tasks = tasks(response);
        if (tasks.isEmpty()) {
            throw new DingTalkOfficialApprovalException("DINGTALK_TASK_NOT_FOUND", "DingTalk process instance has no tasks");
        }

        Map<String, Object> fallback = null;
        for (Map<String, Object> task : tasks) {
            if (!STATUS_RUNNING.equalsIgnoreCase(text(task, "task_status", "status"))) {
                continue;
            }
            if (fallback == null) {
                fallback = task;
            }
            if (StringUtils.hasText(actionerUserId)
                && actionerUserId.equals(text(task, "userid", "userId", "user_id"))) {
                return taskLookupResult(task, false);
            }
        }

        if (fallback != null) {
            return taskLookupResult(fallback, true);
        }
        throw new DingTalkOfficialApprovalException(
            "DINGTALK_RUNNING_TASK_NOT_FOUND",
            "DingTalk process instance has no running task"
        );
    }

    private TaskLookupResult taskLookupResult(Map<String, Object> task, boolean fallback) {
        String taskId = text(task, "taskid", "taskId", "task_id");
        if (!StringUtils.hasText(taskId)) {
            throw new DingTalkOfficialApprovalException(
                "DINGTALK_TASK_ID_MISSING",
                "DingTalk running task does not contain taskId"
            );
        }
        return new TaskLookupResult(taskId, fallback);
    }

    private void ensureSuccess(Map<String, Object> response, String errorCode, String message) {
        Object code = response == null ? null : response.get("errcode");
        if (code == null) {
            code = response == null ? null : response.get("code");
        }
        boolean success = code == null || "0".equals(String.valueOf(code));
        if (!success) {
            String remoteMessage = text(response, "errmsg", "message");
            throw new DingTalkOfficialApprovalException(
                errorCode,
                message + (StringUtils.hasText(remoteMessage) ? ": " + remoteMessage : "")
            );
        }
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> tasks(Map<String, Object> response) {
        Object processInstance = response == null ? null : response.get("process_instance");
        if (processInstance instanceof Map<?, ?> processMap) {
            Object tasks = processMap.get("tasks");
            if (tasks instanceof List<?> taskList) {
                return (List<Map<String, Object>>) tasks;
            }
        }
        Object result = response == null ? null : response.get("result");
        if (result instanceof Map<?, ?> resultMap) {
            Object tasks = resultMap.get("tasks");
            if (tasks instanceof List<?> taskList) {
                return (List<Map<String, Object>>) tasks;
            }
        }
        Object tasks = response == null ? null : response.get("tasks");
        if (tasks instanceof List<?> taskList) {
            return (List<Map<String, Object>>) tasks;
        }
        return List.of();
    }

    private String text(Map<String, Object> value, String... keys) {
        if (value == null) {
            return null;
        }
        for (String key : keys) {
            Object item = value.get(key);
            if (item != null && StringUtils.hasText(String.valueOf(item))) {
                return String.valueOf(item).trim();
            }
        }
        return null;
    }

    private String toJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception ignored) {
            return null;
        }
    }

    public record TaskLookupResult(String taskId, boolean fallback) {}
    public record OfficialAgreeResult(String taskId, String rawResponseJson) {}
}
