package com.yuewei.plm.module.workflow.vo;

import com.yuewei.plm.module.workflow.entity.WorkflowTemplateNode;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class WorkflowTemplateNodeVO {

    private Long workflowNodeId;
    private Long workflowTemplateId;
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
    private String remark;

    public static WorkflowTemplateNodeVO from(WorkflowTemplateNode node) {
        return WorkflowTemplateNodeVO.builder()
            .workflowNodeId(node.getWorkflowNodeId())
            .workflowTemplateId(node.getWorkflowTemplateId())
            .stepNo(node.getStepNo())
            .nodeCode(node.getNodeCode())
            .nodeName(node.getNodeName())
            .stageCode(node.getStageCode())
            .stageName(node.getStageName())
            .phaseName(node.getPhaseName())
            .requiredAttachment(Integer.valueOf(1).equals(node.getRequiredAttachment()))
            .requiredFileCategory(node.getRequiredFileCategory())
            .uploadPrompt(node.getUploadPrompt())
            .confirmPrompt(node.getConfirmPrompt())
            .emptyFileMessage(node.getEmptyFileMessage())
            .gateFlag(Integer.valueOf(1).equals(node.getGateFlag()))
            .enabledFlag(!Integer.valueOf(0).equals(node.getEnabledFlag()))
            .remark(node.getRemark())
            .build();
    }
}
