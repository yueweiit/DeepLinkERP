package com.yuewei.plm.module.bom.controller;

import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.bom.dto.ProductionColorConfirmDTO;
import com.yuewei.plm.module.bom.dto.ProductionOperationConfirmDTO;
import com.yuewei.plm.module.bom.dto.ProductionRouteConfirmDTO;
import com.yuewei.plm.module.bom.service.ProductionConfirmationService;
import com.yuewei.plm.module.bom.vo.ProductionConfirmationVO;
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
@RequestMapping("/api/v1/projects/{projectId}")
public class ProductionConfirmationController {
    private final ProductionConfirmationService service;

    @GetMapping("/production-confirmation")
    public ResponseVO<ProductionConfirmationVO> get(@PathVariable Long projectId, HttpServletRequest request) {
        return ResponseVO.success(service.get(projectId), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/production-operations/confirm")
    public ResponseVO<ProductionConfirmationVO> confirmOperations(@PathVariable Long projectId,
        @Valid @RequestBody ProductionOperationConfirmDTO dto, HttpServletRequest request) {
        return ResponseVO.success(service.confirmOperations(projectId, dto), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/production-routes/confirm")
    public ResponseVO<ProductionConfirmationVO> confirmRoutes(@PathVariable Long projectId,
        @Valid @RequestBody ProductionRouteConfirmDTO dto, HttpServletRequest request) {
        return ResponseVO.success(service.confirmRoutes(projectId, dto), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/production-colors/confirm")
    public ResponseVO<ProductionConfirmationVO> confirmColors(@PathVariable Long projectId,
        @Valid @RequestBody ProductionColorConfirmDTO dto, HttpServletRequest request) {
        return ResponseVO.success(service.confirmColors(projectId, dto), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }
}
