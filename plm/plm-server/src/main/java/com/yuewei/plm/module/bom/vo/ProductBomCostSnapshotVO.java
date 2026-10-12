package com.yuewei.plm.module.bom.vo;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ProductBomCostSnapshotVO {
    private BigDecimal materialCost;
    private BigDecimal lossCost;
    private BigDecimal processCost;
    private BigDecimal packageCost;
    private BigDecimal laborCost;
    private BigDecimal toolingCost;
    private BigDecimal otherCost;
    private BigDecimal totalCost;
    private String currencyCode;
    private LocalDateTime calculatedAt;
}
