package com.yuewei.plm.module.project.vo;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ProjectCostItemVO {
    private Long projectCostItemId;
    private Long productId;
    private String costCategory;
    private String costCategoryName;
    private String costName;
    private BigDecimal amount;
    private String currencyCode;
    private String supplierName;
    private LocalDateTime occurredAt;
    private String status;
    private String statusName;
    private LocalDateTime confirmedAt;
    private String confirmedBy;
    private LocalDateTime voidedAt;
    private String voidedBy;
    private String remark;
    private LocalDateTime createdAt;
    private String createdBy;
    private LocalDateTime updatedAt;
    private String updatedBy;

}
