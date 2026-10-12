package com.yuewei.plm.module.integration.dingtalk.controller;

import com.yuewei.plm.common.constant.ApiConstants;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.integration.dingtalk.config.DingTalkIntegrationProperties;
import com.yuewei.plm.module.integration.dingtalk.dto.DingTalkApprovalCallbackDTO;
import com.yuewei.plm.module.integration.dingtalk.service.DingTalkApprovalDispatchService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import java.time.OffsetDateTime;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.util.StringUtils;

@RestController
@RequiredArgsConstructor
@RequestMapping(ApiConstants.API_V1_PREFIX + "/integrations/dingtalk/approval-callbacks")
public class DingTalkApprovalCallbackController {
    private static final String BEARER_PREFIX = "Bearer ";

    private final DingTalkApprovalDispatchService dispatchService;
    private final DingTalkIntegrationProperties properties;

    @PostMapping
    public ResponseVO<Object> receive(@Valid @RequestBody DingTalkApprovalCallbackDTO dto,
                                      @RequestHeader(value = "Authorization", required = false) String authorization,
                                      HttpServletRequest request) {
        validateCallbackToken(authorization);
        return ResponseVO.success(dispatchService.dispatch(dto), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    private void validateCallbackToken(String authorization) {
        if (!StringUtils.hasText(properties.getCallbackToken())) {
            return;
        }
        String expected = BEARER_PREFIX + properties.getCallbackToken();
        if (!expected.equals(authorization)) {
            throw new BusinessException(ErrorCodeConstants.UNAUTHORIZED, "钉钉回调签名校验失败");
        }
    }
}
