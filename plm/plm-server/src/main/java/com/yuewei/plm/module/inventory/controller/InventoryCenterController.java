package com.yuewei.plm.module.inventory.controller;

import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.common.vo.PageVO;
import com.yuewei.plm.module.inventory.dto.InventoryCenterQueryDTO;
import com.yuewei.plm.module.inventory.service.InventoryCenterService;
import com.yuewei.plm.module.inventory.vo.InventoryCenterSnapshotVO;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import java.util.List;
import java.time.OffsetDateTime;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
@RequestMapping("/api/v1/inventories")
public class InventoryCenterController {

    private final InventoryCenterService inventoryCenterService;

    @GetMapping
    public ResponseVO<PageVO<InventoryCenterSnapshotVO.InventoryListRow>> page(@Valid InventoryCenterQueryDTO query, HttpServletRequest request) {
        return ResponseVO.success(inventoryCenterService.page(query), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @GetMapping("/groups")
    public ResponseVO<List<InventoryCenterSnapshotVO.InventoryTreeNode>> groups(HttpServletRequest request) {
        return ResponseVO.success(inventoryCenterService.groups(), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @GetMapping("/center-snapshot")
    public ResponseVO<InventoryCenterSnapshotVO> snapshot(HttpServletRequest request) {
        return ResponseVO.success(
            inventoryCenterService.snapshot(),
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }
}
