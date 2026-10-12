package com.yuewei.plm.module.project.vo;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class TimelineNodeVO {
    private Integer stepNo;
    private String nodeCode;
    private String nodeName;
    private String stageCode;
    private String stageName;
    private String phaseName;
    private Boolean requiredAttachment;
    private String requiredFileCategory;
    private String uploadPrompt;
    private String confirmPrompt;
    private String emptyFileMessage;
    private Boolean gateFlag;
    private Boolean enabledFlag;
    private String nodeStatus;
    private Integer documentCount;
    private Boolean confirmed;
}
