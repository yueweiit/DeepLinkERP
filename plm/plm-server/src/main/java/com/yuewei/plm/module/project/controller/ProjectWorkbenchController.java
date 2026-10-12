package com.yuewei.plm.module.project.controller;

import com.yuewei.plm.common.constant.ApiConstants;
import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.PageVO;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.project.dto.ProjectQueryDTO;
import com.yuewei.plm.module.project.service.ProjectService;
import com.yuewei.plm.module.project.vo.ProjectSummaryVO;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import java.time.OffsetDateTime;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
@RequestMapping(ApiConstants.API_V1_PREFIX + "/workbench/projects")
public class ProjectWorkbenchController {

    private final ProjectService projectService;

    @GetMapping("/in-progress")
    @Operation(summary = "工作台进行中项目")
    public ResponseVO<PageVO<ProjectSummaryVO>> inProgress(@Valid ProjectQueryDTO queryDTO,
                                                           HttpServletRequest request) {
        return ResponseVO.success(
            projectService.pageInProgress(queryDTO),
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }
}
