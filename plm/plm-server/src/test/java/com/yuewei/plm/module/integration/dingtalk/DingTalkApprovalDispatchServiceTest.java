package com.yuewei.plm.module.integration.dingtalk;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.module.integration.dingtalk.config.DingTalkIntegrationProperties;
import com.yuewei.plm.module.integration.dingtalk.dto.DingTalkApprovalCallbackDTO;
import com.yuewei.plm.module.integration.dingtalk.dto.DingTalkModelVariantReceiveDTO;
import com.yuewei.plm.module.integration.dingtalk.service.DingTalkApprovalDispatchService;
import com.yuewei.plm.module.integration.dingtalk.service.DingTalkModelVariantService;
import com.yuewei.plm.module.integration.dingtalk.service.DingTalkProductLineService;
import com.yuewei.plm.module.integration.dingtalk.vo.DingTalkModelVariantResultVO;
import java.time.LocalDate;
import java.util.LinkedHashMap;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

class DingTalkApprovalDispatchServiceTest {

    @Test
    void modelVariantAcceptsNonZeroPaddedExpectedDeliveryDate() {
        DingTalkIntegrationProperties properties = new DingTalkIntegrationProperties();
        properties.setModelVariantProcessCode("PROC-MODEL");
        DingTalkProductLineService productLineService = mock(DingTalkProductLineService.class);
        DingTalkModelVariantService modelVariantService = mock(DingTalkModelVariantService.class);
        when(modelVariantService.receive(any())).thenReturn(DingTalkModelVariantResultVO.builder().projectId(9L).build());
        DingTalkApprovalDispatchService service = new DingTalkApprovalDispatchService(
            properties,
            productLineService,
            modelVariantService,
            new ObjectMapper()
        );

        service.dispatch(callback("2026-8-30"));

        ArgumentCaptor<DingTalkModelVariantReceiveDTO> captor = ArgumentCaptor.forClass(DingTalkModelVariantReceiveDTO.class);
        verify(modelVariantService).receive(captor.capture());
        assertThat(captor.getValue().getExpectedDeliveryDate()).isEqualTo(LocalDate.of(2026, 8, 30));
    }

    @Test
    void modelVariantUsesProcessInstanceIdAliasAsIdempotencyKey() throws Exception {
        DingTalkIntegrationProperties properties = new DingTalkIntegrationProperties();
        properties.setModelVariantProcessCode("PROC-MODEL");
        DingTalkProductLineService productLineService = mock(DingTalkProductLineService.class);
        DingTalkModelVariantService modelVariantService = mock(DingTalkModelVariantService.class);
        when(modelVariantService.receive(any())).thenReturn(DingTalkModelVariantResultVO.builder().projectId(9L).build());
        ObjectMapper objectMapper = new ObjectMapper();
        DingTalkApprovalDispatchService service = new DingTalkApprovalDispatchService(
            properties,
            productLineService,
            modelVariantService,
            objectMapper
        );
        DingTalkApprovalCallbackDTO dto = objectMapper.readValue("""
            {
              "processCode": "PROC-MODEL",
              "processInstanceId": "ding-process-instance-001",
              "approvalNo": "114",
              "approvalStatus": "approved",
              "form": {
                "parentProductId": 1,
                "tipo": "Fantasia Case",
                "model": "HR X8D",
                "generatedCode": "MFA101291"
              }
            }
            """, DingTalkApprovalCallbackDTO.class);

        service.dispatch(dto);

        ArgumentCaptor<DingTalkModelVariantReceiveDTO> captor = ArgumentCaptor.forClass(DingTalkModelVariantReceiveDTO.class);
        verify(modelVariantService).receive(captor.capture());
        assertThat(captor.getValue().getApprovalInstanceId()).isEqualTo("ding-process-instance-001");
        assertThat(captor.getValue().getDingTalkApprovalNo()).isEqualTo("114");
    }

    private DingTalkApprovalCallbackDTO callback(String expectedDeliveryDate) {
        DingTalkApprovalCallbackDTO dto = new DingTalkApprovalCallbackDTO();
        dto.setProcessCode("PROC-MODEL");
        dto.setApprovalInstanceId("ding-instance-001");
        dto.setApprovalStatus("approved");
        Map<String, Object> form = new LinkedHashMap<>();
        form.put("parentProductId", 1);
        form.put("tipo", "Fantasia Case");
        form.put("model", "HR X8D");
        form.put("generatedCode", "MFA101291");
        form.put("expectedDeliveryDate", expectedDeliveryDate);
        dto.setForm(form);
        return dto;
    }
}
