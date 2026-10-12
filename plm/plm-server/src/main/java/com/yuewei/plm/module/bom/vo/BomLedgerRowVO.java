package com.yuewei.plm.module.bom.vo;

import java.time.LocalDateTime;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class BomLedgerRowVO {
    private Long productBomId;
    private Long productId;
    private String bomCode;
    private String productCode;
    private String productName;
    private String model;
    private String versionNo;
    private Integer routeCount;
    private Integer skuCount;
    private String status;
    private String sourceType;
    private LocalDateTime updatedAt;
}
