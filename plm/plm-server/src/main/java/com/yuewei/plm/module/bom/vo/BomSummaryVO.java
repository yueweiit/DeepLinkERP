package com.yuewei.plm.module.bom.vo;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class BomSummaryVO {
    private BigDecimal testTotalCost;
    private LocalDateTime testCalculatedAt;
    private String testVersionNo;
    private BigDecimal rdTotalCost;
    private BigDecimal formalAverageUnitCost;
    private BigDecimal currentBomSkuUnitCost;
    private List<ProductBomWorkbenchVO> formalVersions;
}
