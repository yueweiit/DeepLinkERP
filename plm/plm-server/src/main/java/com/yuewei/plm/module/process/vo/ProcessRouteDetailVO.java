package com.yuewei.plm.module.process.vo;

import java.math.BigDecimal;
import java.util.List;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ProcessRouteDetailVO {
    private Long routeId;
    private Long processId;
    private String routeCode;
    private String routeName;
    private Long productId;
    private String productCode;
    private String productName;
    private String versionNo;
    private String routeType;
    private String status;
    private String templateSource;
    private String owner;
    private String currentGate;
    private BigDecimal totalCost;
    private Boolean passedGate;
    private Boolean isLocked;
    private Integer differenceOperationCount;
    private String inheritedFrom;
    private String overviewNote;
    private List<ProcessOperationRecordVO> operations;
    private List<Object> confirmations;
    private List<Object> gateChecks;
    private List<Object> attachments;
    private List<Object> changes;
    private List<Object> impacts;
}
