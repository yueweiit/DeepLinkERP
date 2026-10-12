package com.yuewei.plm.module.inventory.vo;

import java.util.List;

public record InventoryCenterSnapshotVO(
    List<InventoryTreeNode> tree,
    List<InventoryListRow> items
) {
    public record InventoryTreeNode(
        String nodeId,
        String label,
        String nodeType,
        Integer count,
        String groupCode,
        List<InventoryTreeNode> children
    ) {
    }

    public record InventoryListRow(
        String itemId,
        String nodeId,
        String code,
        String name,
        String spec,
        String stock,
        String inventoryType,
        String productName,
        String phoneModel,
        String status,
        String supplierName,
        String updatedAt
    ) {
    }
}
