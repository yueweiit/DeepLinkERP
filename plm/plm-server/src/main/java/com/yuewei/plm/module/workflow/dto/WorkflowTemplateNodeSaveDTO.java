package com.yuewei.plm.module.workflow.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

@Data
public class WorkflowTemplateNodeSaveDTO {

    private Long workflowNodeId;
    @NotNull
    private Integer stepNo;
    @NotBlank
    private String nodeCode;
    @NotBlank
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
    private String remark;
}
