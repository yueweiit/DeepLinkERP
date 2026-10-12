package com.yuewei.plm.module.integration.dingtalk;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.module.integration.dingtalk.service.DingTalkAccessTokenService;
import com.yuewei.plm.module.integration.dingtalk.service.DingTalkOfficialApprovalClient;
import com.yuewei.plm.module.integration.dingtalk.service.DingTalkOfficialApprovalException;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class DingTalkOfficialApprovalClientTest {

    private final DingTalkOfficialApprovalClient client = new DingTalkOfficialApprovalClient(
        mock(DingTalkAccessTokenService.class),
        new ObjectMapper()
    );

    @Test
    void extractRunningTaskIdPrefersActionerUserRunningTask() {
        Map<String, Object> response = Map.of(
            "errcode", 0,
            "process_instance", Map.of("tasks", List.of(
                Map.of("taskid", "task-001", "userid", "other-user", "task_status", "RUNNING"),
                Map.of("taskid", "task-002", "userid", "02356802443226388318", "task_status", "RUNNING")
            ))
        );

        var result = client.extractRunningTaskId(response, "02356802443226388318");

        assertThat(result.taskId()).isEqualTo("task-002");
        assertThat(result.fallback()).isFalse();
    }

    @Test
    void extractRunningTaskIdFallsBackToFirstRunningTask() {
        Map<String, Object> response = Map.of(
            "process_instance", Map.of("tasks", List.of(
                Map.of("taskid", "task-001", "userid", "other-user", "task_status", "RUNNING"),
                Map.of("taskid", "task-002", "userid", "another-user", "task_status", "COMPLETED")
            ))
        );

        var result = client.extractRunningTaskId(response, "02356802443226388318");

        assertThat(result.taskId()).isEqualTo("task-001");
        assertThat(result.fallback()).isTrue();
    }

    @Test
    void extractRunningTaskIdFailsWhenNoRunningTaskExists() {
        Map<String, Object> response = Map.of(
            "process_instance", Map.of("tasks", List.of(
                Map.of("taskid", "task-001", "userid", "other-user", "task_status", "COMPLETED")
            ))
        );

        assertThatThrownBy(() -> client.extractRunningTaskId(response, "02356802443226388318"))
            .isInstanceOf(DingTalkOfficialApprovalException.class)
            .extracting("errorCode")
            .isEqualTo("DINGTALK_RUNNING_TASK_NOT_FOUND");
    }
}
