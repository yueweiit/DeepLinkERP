package com.yuewei.plm.module.integration.dingtalk.controller;

import com.yuewei.plm.common.constant.ApiConstants;
import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.common.security.CurrentUserContext;
import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.integration.dingtalk.service.DingTalkShipMoldTriggerService;
import com.yuewei.plm.module.integration.dingtalk.vo.DingTalkOutboundTriggerResultVO;
import jakarta.servlet.http.HttpServletRequest;
import java.time.OffsetDateTime;
import lombok.RequiredArgsConstructor;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
@RequestMapping(ApiConstants.API_V1_PREFIX + "/integrations/dingtalk/model-variant-projects")
public class DingTalkShipMoldTriggerController {
    private final DingTalkShipMoldTriggerService triggerService;

    @PostMapping("/{projectId}/ship-mold/trigger")
    public ResponseVO<DingTalkOutboundTriggerResultVO> trigger(@PathVariable Long projectId, HttpServletRequest request) {
        String operator = CurrentUserContext.get()
            .map(CurrentUser::displayName)
            .filter(StringUtils::hasText)
            .orElse("system");
        return ResponseVO.success(triggerService.retry(projectId, operator), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }
}
