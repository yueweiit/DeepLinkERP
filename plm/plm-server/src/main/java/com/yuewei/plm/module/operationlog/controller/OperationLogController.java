package com.yuewei.plm.module.operationlog.controller;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.constant.ApiConstants;
import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.PageVO;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.operationlog.constant.OperationActionConstants;
import com.yuewei.plm.module.operationlog.dto.OperationLogQueryDTO;
import com.yuewei.plm.module.operationlog.dto.OperationLogTestDTO;
import com.yuewei.plm.module.operationlog.service.OperationLogCreateCommand;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.operationlog.vo.OperationLogVO;
import com.yuewei.plm.module.pilot.PilotAccessService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import java.time.OffsetDateTime;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
@RequestMapping(ApiConstants.API_V1_PREFIX + "/operation-logs")
public class OperationLogController {

    private final OperationLogService operationLogService;
    private final ObjectMapper objectMapper;
    private final PilotAccessService access;

    @GetMapping
    public ResponseVO<PageVO<OperationLogVO>> page(@Valid OperationLogQueryDTO queryDTO, HttpServletRequest request) {
        // Details may contain financial changes; the existing endpoint is administrator-only.
        access.requireAdministrator();
        return ResponseVO.success(operationLogService.page(queryDTO), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/test")
    public ResponseVO<Map<String, Long>> test(@Valid @RequestBody OperationLogTestDTO testDTO, HttpServletRequest request)
            throws JsonProcessingException {
        access.requireAdministrator();
        Long logId = operationLogService.logSuccess(OperationLogCreateCommand.builder()
            .action(OperationActionConstants.TEST_WRITE)
            .businessType(testDTO.getBusinessType())
            .businessId(testDTO.getBusinessId())
            .businessCode(testDTO.getBusinessCode())
            .businessName(testDTO.getBusinessName())
            .detailJson(testDTO.getDetail() == null ? null : objectMapper.writeValueAsString(testDTO.getDetail()))
            .request(request)
            .build());
        return ResponseVO.success(Map.of("logId", logId), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }
}
