package com.yuewei.plm.module.integration.dingtalk;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.yuewei.plm.module.integration.dingtalk.dto.DingTalkOutboundRelayDTO;
import com.yuewei.plm.module.integration.dingtalk.service.DingTalkOfficialApprovalClient;
import com.yuewei.plm.module.integration.dingtalk.service.DingTalkOutboundRelayService;
import java.util.List;
import org.junit.jupiter.api.Test;

class DingTalkOutboundRelayServiceTest {

    private final DingTalkOfficialApprovalClient officialApprovalClient = mock(DingTalkOfficialApprovalClient.class);
    private final DingTalkOutboundRelayService service = new DingTalkOutboundRelayService(officialApprovalClient);

    @Test
    void workflowTaskLookupReturnsTaskIdWhenProvided() {
        DingTalkOutboundRelayDTO dto = new DingTalkOutboundRelayDTO();
        dto.setAction(" workflow-task-lookup ");
        dto.setApprovalInstanceId("ding-instance-001");
        dto.setTaskId("ding-task-001");

        var result = service.handle(dto);

        assertThat(result.getStatus()).isEqualTo("success");
        assertThat(result.getAction()).isEqualTo("workflow-task-lookup");
        assertThat(result.getTaskId()).isEqualTo("ding-task-001");
        assertThat(result.getExternalStatus()).isEqualTo("success");
        verify(officialApprovalClient, never()).lookupRunningTaskId("ding-instance-001", null);
    }

    @Test
    void workflowTaskLookupWithoutTaskIdQueriesOfficialApi() {
        DingTalkOutboundRelayDTO dto = new DingTalkOutboundRelayDTO();
        dto.setAction("workflow-task-lookup");
        dto.setProcessInstanceId("ding-instance-001");
        dto.setActionerUserId("02356802443226388318");
        when(officialApprovalClient.lookupRunningTaskId("ding-instance-001", "02356802443226388318"))
            .thenReturn(new DingTalkOfficialApprovalClient.TaskLookupResult("ding-task-looked-up", false));

        var result = service.handle(dto);

        assertThat(result.getStatus()).isEqualTo("success");
        assertThat(result.getTaskId()).isEqualTo("ding-task-looked-up");
        assertThat(result.getExternalStatus()).isEqualTo("success");
        assertThat(result.getApprovalInstanceId()).isEqualTo("ding-instance-001");
    }

    @Test
    void agreeRequiresActioner() {
        DingTalkOutboundRelayDTO dto = new DingTalkOutboundRelayDTO();
        dto.setAction("agree");
        dto.setApprovalInstanceId("ding-instance-001");

        var result = service.handle(dto);

        assertThat(result.getStatus()).isEqualTo("failed");
        assertThat(result.getErrorCode()).isEqualTo("DINGTALK_ACTIONER_USER_ID_REQUIRED");
    }

    @Test
    void agreeWithoutTaskIdLooksUpTaskAndExecutesOfficialApi() {
        DingTalkOutboundRelayDTO dto = new DingTalkOutboundRelayDTO();
        dto.setAction("agree");
        dto.setApprovalInstanceId("ding-instance-001");
        dto.setActionerUserId("02356802443226388318");
        dto.setRemark("PLM mold transfer completed");
        when(officialApprovalClient.lookupRunningTaskId("ding-instance-001", "02356802443226388318"))
            .thenReturn(new DingTalkOfficialApprovalClient.TaskLookupResult("ding-task-looked-up", false));
        when(officialApprovalClient.agreeTask(
            "ding-instance-001",
            "ding-task-looked-up",
            "02356802443226388318",
            "PLM mold transfer completed"
        )).thenReturn(new DingTalkOfficialApprovalClient.OfficialAgreeResult("ding-task-looked-up", "{}"));

        var result = service.handle(dto);

        assertThat(result.getStatus()).isEqualTo("success");
        assertThat(result.getTaskId()).isEqualTo("ding-task-looked-up");
        assertThat(result.getExternalStatus()).isEqualTo("success");
    }

    @Test
    void agreeWithTaskIdExecutesOfficialApiDirectly() {
        DingTalkOutboundRelayDTO dto = new DingTalkOutboundRelayDTO();
        dto.setAction("agree");
        dto.setApprovalInstanceId("ding-instance-001");
        dto.setTaskId("ding-task-001");
        dto.setActionerUserId("02356802443226388318");
        when(officialApprovalClient.agreeTask("ding-instance-001", "ding-task-001", "02356802443226388318", null))
            .thenReturn(new DingTalkOfficialApprovalClient.OfficialAgreeResult("ding-task-001", "{}"));

        var result = service.handle(dto);

        assertThat(result.getStatus()).isEqualTo("success");
        assertThat(result.getTaskId()).isEqualTo("ding-task-001");
        verify(officialApprovalClient, never()).lookupRunningTaskId("ding-instance-001", "02356802443226388318");
    }

    @Test
    void ccRequiresReceiversAndReportsOfficialApiNotConnected() {
        DingTalkOutboundRelayDTO dto = new DingTalkOutboundRelayDTO();
        dto.setAction("cc");
        dto.setApprovalInstanceId("ding-instance-001");
        dto.setReceiverUserIds(List.of("02356802443226388318"));

        var result = service.handle(dto);

        assertThat(result.getStatus()).isEqualTo("failed");
        assertThat(result.getErrorCode()).isEqualTo("DINGTALK_CC_NOT_IMPLEMENTED");
    }
}
