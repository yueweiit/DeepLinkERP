package com.yuewei.plm.module.project.vo;

import java.time.LocalDateTime;
import java.time.LocalDate;
import java.util.List;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class TimelineDetailVO {
    private Long projectId;
    private Long productId;
    private String projectCode;
    private String projectName;
    private String productType;
    private LocalDate expectedDeliveryDate;
    private String sourceSystem;
    private String sourceInstanceId;
    private String sourceFormUrl;
    private Boolean started;
    private String startBlockReason;
    private Boolean timelineCompleted;
    private Integer currentStepNo;
    private String currentStageCode;
    private String currentStageName;
    private String currentPhaseName;
    private String currentStepCode;
    private String currentStepName;
    private Boolean currentConfirmed;
    private String confirmedNodeKey;
    private String lastAction;
    private String lastReason;
    private LocalDateTime lastOperatedAt;
    private Long lastOperatorUserId;
    private String lastOperatorUserName;
    private MoldTransferExpressVO moldTransferExpress;
    private List<TimelineNodeVO> nodes;
}
