package com.yuewei.plm.module.project.controller;

import com.yuewei.plm.common.constant.ApiConstants;
import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.PageVO;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.project.dto.ProjectQueryDTO;
import com.yuewei.plm.module.project.service.ProjectService;
import com.yuewei.plm.module.project.vo.ProjectDetailVO;
import com.yuewei.plm.module.project.vo.ProjectSummaryVO;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import java.time.OffsetDateTime;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
@RequestMapping(ApiConstants.API_V1_PREFIX + "/projects")
public class ProjectController {

    private final ProjectService projectService;

    @GetMapping
    @Operation(summary = "项目列表")
    public ResponseVO<PageVO<ProjectSummaryVO>> list(@Valid ProjectQueryDTO queryDTO,
                                                     HttpServletRequest request) {
        return ResponseVO.success(projectService.page(queryDTO), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @GetMapping("/{projectId}")
    @Operation(summary = "项目详情")
    public ResponseVO<ProjectDetailVO> detail(@PathVariable Long projectId, HttpServletRequest request) {
        return ResponseVO.success(projectService.getDetail(projectId), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @GetMapping("/{projectId}/summary")
    @Operation(summary = "项目摘要")
    public ResponseVO<ProjectSummaryVO> summary(@PathVariable Long projectId, HttpServletRequest request) {
        return ResponseVO.success(projectService.getSummary(projectId), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }
}
