package com.yuewei.plm.module.project.vo;

import java.time.LocalDateTime;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ProjectSummaryVO {
    private Long projectId;
    private Long productId;
    private Long parentProductId;
    private String productCode;
    private String productSpecificCode;
    private String phoneModelCode;
    private String colorCode;
    private String finishedProductCode;
    private String importShortCode;
    private String productName;
    private String productType;
    private String productTypeName;
    private String model;
    private String moldCodes;
    private String color;
    private String versionNo;
    private String status;
    private String statusName;
    private String lockStatus;
    private LocalDateTime abandonedAt;
    private String abandonedBy;
    private String abandonReason;
    private Long ownerUserId;
    private String ownerUserName;
    private Integer currentStepNo;
    private String currentNodeName;
    private LocalDateTime moldTransferAt;
    private LocalDateTime expectedArrivalAt;
    private LocalDateTime actualArrivalAt;
    private Integer documentCount;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
