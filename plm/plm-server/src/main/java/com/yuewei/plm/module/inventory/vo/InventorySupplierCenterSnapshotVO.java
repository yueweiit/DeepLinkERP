package com.yuewei.plm.module.inventory.vo;

import java.math.BigDecimal;
import java.util.List;

public record InventorySupplierCenterSnapshotVO(
    List<Metric> metrics,
    List<SupplierDetail> suppliers,
    List<RiskItem> risks
) {

    public record Metric(
        String label,
        String value,
        String hint,
        String targetPath
    ) {
    }

    public record SupplierDetail(
        Long supplierId,
        String supplierCode,
        String supplierName,
        String shortName,
        String contactPerson,
        String contactPhone,
        String contactEmail,
        List<String> supplyCategories,
        String region,
        String status,
        String updatedAt,
        String cooperationLevel,
        String paymentTerm,
        String deliveryRisk,
        List<SupplyRecord> supplyRecords,
        List<ProjectItem> relatedProjects,
        List<QualificationItem> qualificationFiles
    ) {
    }

    public record SupplyRecord(
        Long recordId,
        String supplyType,
        String itemCode,
        String itemName,
        String relatedProduct,
        BigDecimal unitPrice,
        String currency,
        String lastDeliveryDate,
        String status,
        String targetPath
    ) {
    }

    public record ProjectItem(
        String projectCode,
        String projectName,
        String roleSummary,
        String stage,
        String targetPath
    ) {
    }

    public record QualificationItem(
        String fileName,
        String fileType,
        String validUntil,
        String statusLabel
    ) {
    }

    public record RiskItem(
        String title,
        String level,
        String owner,
        String action,
        String targetPath
    ) {
    }
}
