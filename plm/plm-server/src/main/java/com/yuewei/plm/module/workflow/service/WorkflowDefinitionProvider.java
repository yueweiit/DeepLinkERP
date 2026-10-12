package com.yuewei.plm.module.workflow.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.yuewei.plm.module.project.constant.TimelineNodeConstants.TimelineNodeDefinition;
import com.yuewei.plm.module.workflow.entity.WorkflowTemplate;
import com.yuewei.plm.module.workflow.entity.WorkflowTemplateNode;
import com.yuewei.plm.module.workflow.repository.WorkflowTemplateNodeRepository;
import com.yuewei.plm.repository.entity.Product;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

@Component
@RequiredArgsConstructor
public class WorkflowDefinitionProvider {

    private final WorkflowTemplateService workflowTemplateService;
    private final WorkflowTemplateNodeRepository nodeRepository;

    public List<TimelineNodeDefinition> getDefinitions(String flowType) {
        WorkflowTemplate template = workflowTemplateService.findActiveTemplate(flowType);
        return definitions(template);
    }

    public List<TimelineNodeDefinition> getDefinitions(Product product) {
        WorkflowTemplate template = workflowTemplateService.findTemplateForProduct(product);
        return definitions(template);
    }

    private List<TimelineNodeDefinition> definitions(WorkflowTemplate template) {
        if (template == null) {
            return List.of();
        }
        return nodeRepository.selectList(new LambdaQueryWrapper<WorkflowTemplateNode>()
                .eq(WorkflowTemplateNode::getWorkflowTemplateId, template.getWorkflowTemplateId())
                .eq(WorkflowTemplateNode::getDeletedFlag, 0)
                .eq(WorkflowTemplateNode::getEnabledFlag, 1)
                .orderByAsc(WorkflowTemplateNode::getStepNo))
            .stream()
            .map(this::toDefinition)
            .toList();
    }

    private TimelineNodeDefinition toDefinition(WorkflowTemplateNode node) {
        boolean required = Integer.valueOf(1).equals(node.getRequiredAttachment());
        return new TimelineNodeDefinition(
            node.getStepNo(),
            node.getNodeCode(),
            node.getNodeName(),
            node.getStageCode(),
            node.getStageName(),
            node.getPhaseName(),
            required && StringUtils.hasText(node.getRequiredFileCategory()) ? node.getRequiredFileCategory() : null,
            required,
            node.getUploadPrompt(),
            node.getConfirmPrompt(),
            node.getEmptyFileMessage(),
            Integer.valueOf(1).equals(node.getGateFlag()),
            !Integer.valueOf(0).equals(node.getEnabledFlag())
        );
    }
}
