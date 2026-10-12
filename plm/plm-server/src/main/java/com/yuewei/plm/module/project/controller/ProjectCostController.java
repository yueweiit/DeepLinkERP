package com.yuewei.plm.module.project.controller;

import com.yuewei.plm.common.constant.ApiConstants;
import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.project.dto.ProjectCostItemCreateDTO;
import com.yuewei.plm.module.project.dto.ProjectCostItemUpdateDTO;
import com.yuewei.plm.module.project.service.ProjectCostService;
import com.yuewei.plm.module.project.vo.ProjectCostItemVO;
import com.yuewei.plm.module.project.vo.ProjectCostSummaryVO;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import java.time.OffsetDateTime;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
@RequestMapping(ApiConstants.API_V1_PREFIX + "/projects")
public class ProjectCostController {

    private final ProjectCostService projectCostService;

    @GetMapping("/{projectId}/cost-summary")
    public ResponseVO<ProjectCostSummaryVO> summary(@PathVariable Long projectId, HttpServletRequest request) {
        return ResponseVO.success(projectCostService.getSummary(projectId), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @GetMapping("/{projectId}/cost-items")
    public ResponseVO<List<ProjectCostItemVO>> items(@PathVariable Long projectId, HttpServletRequest request) {
        return ResponseVO.success(projectCostService.listItems(projectId), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/{projectId}/cost-items")
    public ResponseVO<ProjectCostItemVO> create(@PathVariable Long projectId,
                                                @Valid @RequestBody ProjectCostItemCreateDTO dto,
                                                HttpServletRequest request) {
        return ResponseVO.created(projectCostService.createItem(projectId, dto, request), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PutMapping("/{projectId}/cost-items/{costItemId}")
    public ResponseVO<ProjectCostItemVO> update(@PathVariable Long projectId,
                                                @PathVariable Long costItemId,
                                                @Valid @RequestBody ProjectCostItemUpdateDTO dto,
                                                HttpServletRequest request) {
        return ResponseVO.success(projectCostService.updateItem(projectId, costItemId, dto, request), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/{projectId}/cost-items/{costItemId}/confirm")
    public ResponseVO<ProjectCostItemVO> confirm(@PathVariable Long projectId,
                                                 @PathVariable Long costItemId,
                                                 HttpServletRequest request) {
        return ResponseVO.success(projectCostService.confirmItem(projectId, costItemId, request), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/{projectId}/cost-items/{costItemId}/void")
    public ResponseVO<ProjectCostItemVO> voidItem(@PathVariable Long projectId,
                                                  @PathVariable Long costItemId,
                                                  HttpServletRequest request) {
        return ResponseVO.success(projectCostService.voidItem(projectId, costItemId, request), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }
}
