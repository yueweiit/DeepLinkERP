package com.yuewei.plm.module.process.controller;

import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.process.service.ProcessCenterService;
import com.yuewei.plm.module.process.vo.ProcessCenterSnapshotVO;
import com.yuewei.plm.module.process.vo.ProcessRouteRelationVO;
import jakarta.servlet.http.HttpServletRequest;
import java.time.OffsetDateTime;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
@RequestMapping("/api/v1")
public class ProcessCenterController {
    private final ProcessCenterService processCenterService;

    @GetMapping("/process-center/snapshot")
    public ResponseVO<ProcessCenterSnapshotVO> snapshot(HttpServletRequest request) {
        return ResponseVO.success(processCenterService.snapshot(), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @GetMapping("/process-routes/{processId}/relations")
    public ResponseVO<ProcessRouteRelationVO> relations(@PathVariable Long processId, HttpServletRequest request) {
        return ResponseVO.success(processCenterService.relations(processId), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }
}
