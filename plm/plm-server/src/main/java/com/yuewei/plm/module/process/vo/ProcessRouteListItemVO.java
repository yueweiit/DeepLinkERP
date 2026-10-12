package com.yuewei.plm.module.process.vo;

import java.util.List;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ProcessRouteListItemVO {
    private Long routeId;
    private Long processId;
    private String routeCode;
    private String routeName;
    private Long productId;
    private String productCode;
    private String productName;
    private String model;
    private String versionNo;
    private String routeType;
    private String status;
    private String templateSource;
    private String owner;
    private Integer operationCount;
    private Integer colorCount;
    private List<ProcessRouteColorVO> colors;
    private Integer skuCount;
    private java.math.BigDecimal totalCost;
    private String currentGate;
    private String riskLevel;
    private Boolean hasExternalOperation;
    private Boolean hasDifferenceOperation;
    private String updatedAt;
    private String targetPath;
}
