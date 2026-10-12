package com.yuewei.plm.module.integration.dingtalk;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;

import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.module.integration.dingtalk.config.DingTalkIntegrationProperties;
import com.yuewei.plm.module.integration.dingtalk.controller.DingTalkOutboundRelayController;
import com.yuewei.plm.module.integration.dingtalk.dto.DingTalkOutboundRelayDTO;
import com.yuewei.plm.module.integration.dingtalk.service.DingTalkOfficialApprovalClient;
import com.yuewei.plm.module.integration.dingtalk.service.DingTalkOutboundRelayService;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;

class DingTalkOutboundRelayControllerTest {

    @Test
    void receiveReturnsSuccessEnvelopeForBusinessFailedResult() {
        DingTalkIntegrationProperties properties = new DingTalkIntegrationProperties();
        DingTalkOutboundRelayController controller = new DingTalkOutboundRelayController(
            new DingTalkOutboundRelayService(mock(DingTalkOfficialApprovalClient.class)),
            properties
        );
        DingTalkOutboundRelayDTO dto = new DingTalkOutboundRelayDTO();
        dto.setAction("agree");
        dto.setApprovalInstanceId("ding-instance-001");

        var response = controller.receive(dto, null, new MockHttpServletRequest());

        assertThat(response.getCode()).isZero();
        assertThat(response.getMessage()).isEqualTo("success");
        assertThat(response.getData().getStatus()).isEqualTo("failed");
        assertThat(response.getData().getErrorCode()).isEqualTo("DINGTALK_ACTIONER_USER_ID_REQUIRED");
    }

    @Test
    void receiveValidatesCallbackTokenWhenConfigured() {
        DingTalkIntegrationProperties properties = new DingTalkIntegrationProperties();
        properties.setCallbackToken("dev-token");
        DingTalkOutboundRelayController controller = new DingTalkOutboundRelayController(
            new DingTalkOutboundRelayService(mock(DingTalkOfficialApprovalClient.class)),
            properties
        );

        assertThatThrownBy(() -> controller.receive(new DingTalkOutboundRelayDTO(), "Bearer wrong", new MockHttpServletRequest()))
            .isInstanceOf(BusinessException.class)
            .extracting("code")
            .isEqualTo(ErrorCodeConstants.UNAUTHORIZED);
    }
}
