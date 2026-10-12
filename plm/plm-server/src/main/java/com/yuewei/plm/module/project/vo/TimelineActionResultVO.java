package com.yuewei.plm.module.project.vo;

import lombok.Builder;
import lombok.Data;
import java.util.List;

@Data
@Builder
public class TimelineActionResultVO {

    private Long projectId;
    private Long productId;
    private String action;
    private String nodeKey;
    private Integer beforeStepNo;
    private Integer currentStepNo;
    private String currentNodeKey;
    private String currentNodeName;
    private Boolean currentConfirmed;
    private String productStatus;
    private Long logId;
    private List<String> warnings;
}
