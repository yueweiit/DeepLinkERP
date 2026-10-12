package com.yuewei.plm.module.integration.dingtalk.controller;

import com.yuewei.plm.common.constant.ApiConstants;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.integration.dingtalk.config.DingTalkIntegrationProperties;
import com.yuewei.plm.module.integration.dingtalk.dto.DingTalkOutboundRelayDTO;
import com.yuewei.plm.module.integration.dingtalk.service.DingTalkOutboundRelayService;
import com.yuewei.plm.module.integration.dingtalk.vo.DingTalkOutboundRelayResultVO;
import jakarta.servlet.http.HttpServletRequest;
import java.time.OffsetDateTime;
import lombok.RequiredArgsConstructor;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
@RequestMapping({ApiConstants.API_V1_PREFIX + "/integrations/dingtalk/outbound", "/api/dingtalk/outbound"})
public class DingTalkOutboundRelayController {
    private static final String BEARER_PREFIX = "Bearer ";

    private final DingTalkOutboundRelayService relayService;
    private final DingTalkIntegrationProperties properties;

    @GetMapping
    public ResponseVO<DingTalkOutboundRelayResultVO> health(HttpServletRequest request) {
        DingTalkOutboundRelayResultVO result = DingTalkOutboundRelayResultVO.builder()
            .status("success")
            .action("health")
            .externalStatus("ready")
            .message("DingTalk outbound relay endpoint is ready. Use POST with JSON payload.")
            .build();
        return ResponseVO.success(result, RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping
    public ResponseVO<DingTalkOutboundRelayResultVO> receive(
        @RequestBody DingTalkOutboundRelayDTO dto,
        @RequestHeader(value = "Authorization", required = false) String authorization,
        HttpServletRequest request
    ) {
        validateCallbackToken(authorization);
        return ResponseVO.success(relayService.handle(dto), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    private void validateCallbackToken(String authorization) {
        if (!StringUtils.hasText(properties.getCallbackToken())) {
            return;
        }
        String expected = BEARER_PREFIX + properties.getCallbackToken();
        if (!expected.equals(authorization)) {
            throw new BusinessException(ErrorCodeConstants.UNAUTHORIZED, "DingTalk outbound relay token validation failed");
        }
    }
}
