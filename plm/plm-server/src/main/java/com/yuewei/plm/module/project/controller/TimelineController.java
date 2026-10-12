package com.yuewei.plm.module.project.controller;

import com.yuewei.plm.common.constant.ApiConstants;
import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.project.dto.TimelineActionDTO;
import com.yuewei.plm.module.project.service.TimelineActionService;
import com.yuewei.plm.module.project.service.TimelineService;
import com.yuewei.plm.module.project.vo.TimelineActionResultVO;
import com.yuewei.plm.module.project.vo.TimelineDetailVO;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import java.time.OffsetDateTime;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
@RequestMapping(ApiConstants.API_V1_PREFIX + "/projects")
public class TimelineController {

    private final TimelineService timelineService;
    private final TimelineActionService timelineActionService;

    @GetMapping("/{projectId}/timeline")
    @Operation(summary = "Project timeline")
    public ResponseVO<TimelineDetailVO> timeline(@PathVariable Long projectId, HttpServletRequest request) {
        return ResponseVO.success(timelineService.getTimeline(projectId), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/{projectId}/timeline/{nodeKey}/confirm")
    @Operation(summary = "Confirm current timeline node")
    public ResponseVO<TimelineActionResultVO> confirm(
        @PathVariable Long projectId,
        @PathVariable String nodeKey,
        @RequestBody(required = false) TimelineActionDTO dto,
        HttpServletRequest request
    ) {
        return ResponseVO.success(
            timelineActionService.confirm(projectId, nodeKey, dto, request),
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }

    @PostMapping("/{projectId}/timeline/{nodeKey}/advance")
    @Operation(summary = "Advance current timeline node")
    public ResponseVO<TimelineActionResultVO> advance(
        @PathVariable Long projectId,
        @PathVariable String nodeKey,
        @RequestBody(required = false) TimelineActionDTO dto,
        HttpServletRequest request
    ) {
        return ResponseVO.success(
            timelineActionService.advance(projectId, nodeKey, dto, request),
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }

    @PostMapping("/{projectId}/timeline/{nodeKey}/return")
    @Operation(summary = "Return current timeline node")
    public ResponseVO<TimelineActionResultVO> returnNode(
        @PathVariable Long projectId,
        @PathVariable String nodeKey,
        @RequestBody(required = false) TimelineActionDTO dto,
        HttpServletRequest request
    ) {
        return ResponseVO.success(
            timelineActionService.returnNode(projectId, nodeKey, dto, request),
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }
}
