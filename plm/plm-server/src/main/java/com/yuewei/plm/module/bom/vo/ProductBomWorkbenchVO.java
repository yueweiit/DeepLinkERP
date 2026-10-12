package com.yuewei.plm.module.bom.vo;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ProductBomWorkbenchVO {
    private Long productBomId;
    private Long productId;
    private String bomCode;
    private String bomName;
    private String bomScope;
    private String versionNo;
    private String status;
    private BigDecimal testTotalCost;
    private BigDecimal rdTotalCost;
    private BigDecimal formalAverageUnitCost;
    private BigDecimal currentBomSkuUnitCost;
    private LocalDateTime calculatedAt;
    private List<ProductBomItemVO> testItems;
    private List<ProductBomRouteVO> routes;
}
