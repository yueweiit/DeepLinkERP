package com.yuewei.plm.module.integration.dingtalk.controller;

import com.yuewei.plm.common.constant.ApiConstants;
import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.integration.dingtalk.dto.DingTalkModelVariantReceiveDTO;
import com.yuewei.plm.module.integration.dingtalk.service.DingTalkModelVariantService;
import com.yuewei.plm.module.integration.dingtalk.vo.DingTalkModelVariantResultVO;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import java.time.OffsetDateTime;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController @RequiredArgsConstructor
@RequestMapping(ApiConstants.API_V1_PREFIX + "/integrations/dingtalk/model-variant-approvals")
public class DingTalkModelVariantController {
    private final DingTalkModelVariantService service;
    @PostMapping public ResponseVO<DingTalkModelVariantResultVO> receive(@Valid @RequestBody DingTalkModelVariantReceiveDTO dto, HttpServletRequest request) {
        return ResponseVO.success(service.receive(dto), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }
}
