package com.yuewei.plm.module.project.variant.controller;

import com.yuewei.plm.common.constant.ApiConstants;
import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.integration.dingtalk.service.DingTalkModelVariantService;
import com.yuewei.plm.module.project.variant.dto.RequirementFormSaveDTO;
import com.yuewei.plm.module.project.variant.vo.RequirementFormVO;
import jakarta.servlet.http.HttpServletRequest;
import java.time.OffsetDateTime;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

@RestController @RequiredArgsConstructor
@RequestMapping(ApiConstants.API_V1_PREFIX + "/projects/{projectId}/requirement-form")
public class RequirementFormController {
    private final DingTalkModelVariantService service;
    @GetMapping public ResponseVO<RequirementFormVO> get(@PathVariable Long projectId, HttpServletRequest request) { return ResponseVO.success(service.getRequirementForm(projectId), RequestIdUtil.getRequestId(request), OffsetDateTime.now()); }
    @PutMapping public ResponseVO<RequirementFormVO> save(@PathVariable Long projectId, @RequestBody RequirementFormSaveDTO dto, HttpServletRequest request) { return ResponseVO.success(service.saveRequirementForm(projectId, dto), RequestIdUtil.getRequestId(request), OffsetDateTime.now()); }
    @PostMapping("/confirm") public ResponseVO<RequirementFormVO> confirm(@PathVariable Long projectId, @RequestBody RequirementFormSaveDTO dto, HttpServletRequest request) { return ResponseVO.success(service.confirmRequirementForm(projectId, dto), RequestIdUtil.getRequestId(request), OffsetDateTime.now()); }
}
