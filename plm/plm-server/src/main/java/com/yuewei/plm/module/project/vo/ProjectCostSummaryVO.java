package com.yuewei.plm.module.project.vo;

import java.math.BigDecimal;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ProjectCostSummaryVO {
    private Long projectId;
    private Long productId;
    private BigDecimal bomCost;
    private BigDecimal rdCost;
    private BigDecimal moldCost;
    private BigDecimal otherCost;
    private BigDecimal totalCost;
    private String currencyCode;
    private Integer manualItemCount;
    private Integer confirmedManualItemCount;
    private java.util.List<java.util.Map<String,Object>> currencyGroups;
    private String summaryNote;
}
