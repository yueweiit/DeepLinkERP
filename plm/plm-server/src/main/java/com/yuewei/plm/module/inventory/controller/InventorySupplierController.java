package com.yuewei.plm.module.inventory.controller;

import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.inventory.dto.SupplierSupplySideSaveDTO;
import com.yuewei.plm.module.inventory.service.InventorySupplierService;
import com.yuewei.plm.module.inventory.vo.InventorySupplierCenterSnapshotVO;
import com.yuewei.plm.module.inventory.vo.InventorySupplierCenterSnapshotVO.SupplierDetail;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import java.time.OffsetDateTime;
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
@RequestMapping("/api/v1/inventories/suppliers")
public class InventorySupplierController {

    private final InventorySupplierService inventorySupplierService;

    @GetMapping("/snapshot")
    public ResponseVO<InventorySupplierCenterSnapshotVO> snapshot(HttpServletRequest request) {
        return ResponseVO.success(
            inventorySupplierService.snapshot(),
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }

    @PostMapping
    public ResponseVO<SupplierDetail> create(
        @Valid @RequestBody SupplierSupplySideSaveDTO dto,
        HttpServletRequest request
    ) {
        return ResponseVO.created(
            inventorySupplierService.create(dto, request),
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }

    @PutMapping("/{supplierCode}")
    public ResponseVO<SupplierDetail> update(
        @PathVariable String supplierCode,
        @Valid @RequestBody SupplierSupplySideSaveDTO dto,
        HttpServletRequest request
    ) {
        return ResponseVO.success(
            inventorySupplierService.update(supplierCode, dto, request),
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }
}
