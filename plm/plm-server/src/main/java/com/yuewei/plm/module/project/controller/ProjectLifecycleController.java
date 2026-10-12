package com.yuewei.plm.module.project.controller;

import com.yuewei.plm.common.constant.ApiConstants;
import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.controller.dto.ProductLifecycleActionDTO;
import com.yuewei.plm.service.ProductService;
import com.yuewei.plm.service.vo.ProductReleaseGateCheckVO;
import com.yuewei.plm.service.vo.ProductVO;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
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
public class ProjectLifecycleController {

    private final ProductService productService;

    @GetMapping("/{projectId}/release-gate")
    public ResponseVO<ProductReleaseGateCheckVO> checkReleaseGate(@PathVariable Long projectId, HttpServletRequest request) {
        return ResponseVO.success(productService.checkReleaseGate(projectId), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/{projectId}/freeze")
    public ResponseVO<ProductVO> freeze(@PathVariable Long projectId,
                                        @Valid @RequestBody(required = false) ProductLifecycleActionDTO dto,
                                        HttpServletRequest request) {
        return ResponseVO.success(productService.freeze(projectId, dto, request), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/{projectId}/publish")
    public ResponseVO<ProductVO> publish(@PathVariable Long projectId,
                                         @Valid @RequestBody(required = false) ProductLifecycleActionDTO dto,
                                         HttpServletRequest request) {
        return ResponseVO.success(productService.publish(projectId, dto, request), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/{projectId}/archive")
    public ResponseVO<ProductVO> archive(@PathVariable Long projectId,
                                         @Valid @RequestBody(required = false) ProductLifecycleActionDTO dto,
                                         HttpServletRequest request) {
        return ResponseVO.success(productService.archive(projectId, dto, request), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/{projectId}/abandon")
    public ResponseVO<ProductVO> abandon(@PathVariable Long projectId,
                                         @Valid @RequestBody(required = false) ProductLifecycleActionDTO dto,
                                         HttpServletRequest request) {
        return ResponseVO.success(productService.abandon(projectId, dto, request), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }
}
