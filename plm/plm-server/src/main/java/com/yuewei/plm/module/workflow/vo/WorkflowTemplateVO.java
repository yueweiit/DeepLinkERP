package com.yuewei.plm.module.workflow.vo;

import com.yuewei.plm.module.workflow.entity.WorkflowTemplate;
import java.time.LocalDateTime;
import java.util.List;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class WorkflowTemplateVO {

    private Long workflowTemplateId;
    private String flowType;
    private String flowTypeName;
    private String templateName;
    private String versionNo;
    private String status;
    private Boolean activeFlag;
    private String description;
    private Integer nodeCount;
    private LocalDateTime createdAt;
    private String createdBy;
    private LocalDateTime updatedAt;
    private String updatedBy;
    private List<WorkflowTemplateNodeVO> nodes;

    public static WorkflowTemplateVO from(WorkflowTemplate template, List<WorkflowTemplateNodeVO> nodes) {
        return WorkflowTemplateVO.builder()
            .workflowTemplateId(template.getWorkflowTemplateId())
            .flowType(template.getFlowType())
            .flowTypeName(flowTypeName(template.getFlowType()))
            .templateName(template.getTemplateName())
            .versionNo(template.getVersionNo())
            .status(template.getStatus())
            .activeFlag(Integer.valueOf(1).equals(template.getActiveFlag()))
            .description(template.getDescription())
            .nodeCount(nodes == null ? 0 : nodes.size())
            .createdAt(template.getCreatedAt())
            .createdBy(template.getCreatedBy())
            .updatedAt(template.getUpdatedAt())
            .updatedBy(template.getUpdatedBy())
            .nodes(nodes)
            .build();
    }

    private static String flowTypeName(String flowType) {
        if ("product_line".equals(flowType)) {
            return "新产品线";
        }
        if ("model_variant".equals(flowType)) {
            return "新型号线";
        }
        return flowType;
    }
}
