package com.yuewei.plm.module.process.controller;

import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.process.dto.ProcessOperationMasterSaveDTO;
import com.yuewei.plm.module.process.service.ProcessOperationMasterService;
import com.yuewei.plm.module.process.vo.ProcessOperationMasterVO;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import java.time.OffsetDateTime;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@Validated
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/v1/process-operation-masters")
public class ProcessOperationMasterController {

    private final ProcessOperationMasterService processOperationMasterService;

    @GetMapping
    public ResponseVO<List<ProcessOperationMasterVO>> list(@RequestParam(required = false) String keyword,
                                                           @RequestParam(required = false) String processCategory,
                                                           @RequestParam(required = false) String operationType,
                                                           @RequestParam(required = false) String status,
                                                           HttpServletRequest request) {
        return ResponseVO.success(
            processOperationMasterService.list(keyword, processCategory, operationType, status),
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }

    @PostMapping
    public ResponseVO<ProcessOperationMasterVO> create(@Valid @RequestBody ProcessOperationMasterSaveDTO dto,
                                                       HttpServletRequest request) {
        return ResponseVO.success(processOperationMasterService.create(dto), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PutMapping("/{processId}")
    public ResponseVO<ProcessOperationMasterVO> update(@PathVariable Long processId,
                                                       @Valid @RequestBody ProcessOperationMasterSaveDTO dto,
                                                       HttpServletRequest request) {
        return ResponseVO.success(processOperationMasterService.update(processId, dto), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/{processId}/confirm")
    public ResponseVO<ProcessOperationMasterVO> confirm(@PathVariable Long processId, HttpServletRequest request) {
        return ResponseVO.success(processOperationMasterService.confirm(processId), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/{processId}/archive")
    public ResponseVO<ProcessOperationMasterVO> archive(@PathVariable Long processId, HttpServletRequest request) {
        return ResponseVO.success(processOperationMasterService.archive(processId), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }
}
