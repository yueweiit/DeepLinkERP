package com.yuewei.plm.module.workflow.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.common.security.CurrentUserContext;
import com.yuewei.plm.module.operationlog.constant.OperationActionConstants;
import com.yuewei.plm.module.operationlog.service.OperationLogCreateCommand;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.project.constant.TimelineNodeConstants;
import com.yuewei.plm.module.workflow.dto.WorkflowTemplateNodeSaveDTO;
import com.yuewei.plm.module.workflow.dto.WorkflowTemplateSaveDTO;
import com.yuewei.plm.module.workflow.entity.WorkflowTemplate;
import com.yuewei.plm.module.workflow.entity.WorkflowTemplateNode;
import com.yuewei.plm.module.workflow.repository.WorkflowTemplateNodeRepository;
import com.yuewei.plm.module.workflow.repository.WorkflowTemplateRepository;
import com.yuewei.plm.module.workflow.service.WorkflowTemplateService;
import com.yuewei.plm.module.workflow.vo.WorkflowTemplateNodeVO;
import com.yuewei.plm.module.workflow.vo.WorkflowTemplateVO;
import com.yuewei.plm.repository.entity.BaseEntity;
import com.yuewei.plm.repository.entity.Product;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

@Service
@RequiredArgsConstructor
public class WorkflowTemplateServiceImpl implements WorkflowTemplateService {

    private static final String STATUS_DRAFT = "draft";
    private static final String STATUS_ACTIVE = "active";
    private static final String STATUS_INACTIVE = "inactive";

    private final WorkflowTemplateRepository templateRepository;
    private final WorkflowTemplateNodeRepository nodeRepository;
    private final OperationLogService operationLogService;

    @Override
    @Transactional
    public List<WorkflowTemplateVO> list(String flowType, String status) {
        ensureDefaultTemplates(flowType, status);
        LambdaQueryWrapper<WorkflowTemplate> wrapper = new LambdaQueryWrapper<WorkflowTemplate>()
            .eq(WorkflowTemplate::getDeletedFlag, 0)
            .eq(StringUtils.hasText(flowType), WorkflowTemplate::getFlowType, flowType)
            .eq(StringUtils.hasText(status), WorkflowTemplate::getStatus, status)
            .orderByDesc(WorkflowTemplate::getActiveFlag)
            .orderByDesc(WorkflowTemplate::getUpdatedAt);
        return templateRepository.selectList(wrapper).stream()
            .map(template -> WorkflowTemplateVO.from(template, nodeVOs(template.getWorkflowTemplateId())))
            .toList();
    }

    @Override
    public WorkflowTemplateVO detail(Long workflowTemplateId) {
        WorkflowTemplate template = getTemplateOrThrow(workflowTemplateId);
        return WorkflowTemplateVO.from(template, nodeVOs(workflowTemplateId));
    }

    @Override
    @Transactional
    public WorkflowTemplateVO create(WorkflowTemplateSaveDTO dto) {
        validateTemplate(dto);
        WorkflowTemplate template = new WorkflowTemplate();
        template.setFlowType(dto.getFlowType());
        template.setTemplateName(dto.getTemplateName().trim());
        template.setVersionNo(StringUtils.hasText(dto.getVersionNo()) ? dto.getVersionNo().trim() : "V1");
        template.setStatus(statusOrDraft(dto.getStatus()));
        template.setActiveFlag(0);
        template.setDescription(dto.getDescription());
        fillCreateAudit(template);
        templateRepository.insert(template);
        replaceNodes(template.getWorkflowTemplateId(), dto.getNodes());
        writeLog(OperationActionConstants.WORKFLOW_TEMPLATE_CREATE, template, "{\"action\":\"create\"}");
        return detail(template.getWorkflowTemplateId());
    }

    @Override
    @Transactional
    public WorkflowTemplateVO update(Long workflowTemplateId, WorkflowTemplateSaveDTO dto) {
        WorkflowTemplate template = getTemplateOrThrow(workflowTemplateId);
        validateTemplate(dto);
        if (!template.getFlowType().equals(dto.getFlowType())) {
            throw validation("流程线不能在编辑时切换，请使用复制模板");
        }
        template.setTemplateName(dto.getTemplateName().trim());
        if (StringUtils.hasText(dto.getVersionNo())) {
            template.setVersionNo(dto.getVersionNo().trim());
        }
        if (!Integer.valueOf(1).equals(template.getActiveFlag())) {
            template.setStatus(statusOrDraft(dto.getStatus()));
        }
        template.setDescription(dto.getDescription());
        fillUpdateAudit(template);
        templateRepository.updateById(template);
        replaceNodes(workflowTemplateId, dto.getNodes());
        writeLog(OperationActionConstants.WORKFLOW_TEMPLATE_UPDATE, template, "{\"action\":\"update\"}");
        return detail(workflowTemplateId);
    }

    @Override
    @Transactional
    public WorkflowTemplateVO activate(Long workflowTemplateId) {
        WorkflowTemplate template = getTemplateOrThrow(workflowTemplateId);
        List<WorkflowTemplateNode> nodes = nodes(workflowTemplateId, true);
        if (nodes.isEmpty()) {
            throw validation("启用模板前至少需要一个启用节点");
        }
        validateStepContinuity(nodes);
        templateRepository.update(null, new LambdaUpdateWrapper<WorkflowTemplate>()
            .set(WorkflowTemplate::getActiveFlag, 0)
            .set(WorkflowTemplate::getStatus, STATUS_INACTIVE)
            .set(WorkflowTemplate::getUpdatedAt, LocalDateTime.now())
            .set(WorkflowTemplate::getUpdatedBy, currentUserName())
            .eq(WorkflowTemplate::getFlowType, template.getFlowType())
            .eq(WorkflowTemplate::getDeletedFlag, 0)
            .eq(WorkflowTemplate::getActiveFlag, 1));

        template.setActiveFlag(1);
        template.setStatus(STATUS_ACTIVE);
        fillUpdateAudit(template);
        templateRepository.updateById(template);
        writeLog(OperationActionConstants.WORKFLOW_TEMPLATE_ACTIVATE, template, "{\"action\":\"activate\"}");
        return detail(workflowTemplateId);
    }

    @Override
    @Transactional
    public WorkflowTemplateVO copy(Long workflowTemplateId, String targetFlowType) {
        WorkflowTemplate source = getTemplateOrThrow(workflowTemplateId);
        String flowType = StringUtils.hasText(targetFlowType) ? targetFlowType.trim() : source.getFlowType();
        ensureFlowType(flowType);
        WorkflowTemplateSaveDTO dto = new WorkflowTemplateSaveDTO();
        dto.setFlowType(flowType);
        dto.setTemplateName(source.getTemplateName() + " 副本");
        dto.setVersionNo(nextDraftVersion(source.getVersionNo()));
        dto.setStatus(STATUS_DRAFT);
        dto.setDescription(source.getDescription());
        List<WorkflowTemplateNodeSaveDTO> copiedNodes = nodes(source.getWorkflowTemplateId(), false).stream()
            .map(this::copyNode)
            .toList();
        dto.setNodes(copiedNodes);
        WorkflowTemplateVO copied = create(dto);
        writeLog(OperationActionConstants.WORKFLOW_TEMPLATE_COPY, source,
            "{\"action\":\"copy\",\"targetTemplateId\":" + copied.getWorkflowTemplateId() + "}");
        return copied;
    }

    @Override
    public WorkflowTemplate findActiveTemplate(String flowType) {
        ensureFlowType(flowType);
        return first(templateRepository.selectList(new LambdaQueryWrapper<WorkflowTemplate>()
            .eq(WorkflowTemplate::getFlowType, flowType)
            .eq(WorkflowTemplate::getActiveFlag, 1)
            .eq(WorkflowTemplate::getDeletedFlag, 0)
            .orderByDesc(WorkflowTemplate::getUpdatedAt)));
    }

    @Override
    public WorkflowTemplate findTemplateForProduct(Product product) {
        if (product == null) {
            return null;
        }
        if (!Set.of("released", "archived").contains(product.getStatus())) {
            WorkflowTemplate active = findActiveTemplate(product.getProductType());
            if (active != null) {
                return active;
            }
        }
        Long templateId = product.getWorkflowTemplateId();
        if (templateId != null) {
            WorkflowTemplate template = templateRepository.selectById(templateId);
            if (template != null && !Integer.valueOf(1).equals(template.getDeletedFlag())) {
                return template;
            }
        }
        return findActiveTemplate(product.getProductType());
    }

    private List<WorkflowTemplateNodeVO> nodeVOs(Long workflowTemplateId) {
        return nodes(workflowTemplateId, false).stream()
            .map(WorkflowTemplateNodeVO::from)
            .toList();
    }

    private void ensureDefaultTemplates(String flowType, String status) {
        if (StringUtils.hasText(status) && !STATUS_ACTIVE.equals(status)) {
            return;
        }
        if (!StringUtils.hasText(flowType) || TimelineNodeConstants.PRODUCT_TYPE_PRODUCT_LINE.equals(flowType)) {
            ensureDefaultTemplate(
                TimelineNodeConstants.PRODUCT_TYPE_PRODUCT_LINE,
                "新产品线标准流程",
                "审批中心默认新产品线流程模板",
                TimelineNodeConstants.PRODUCT_LINE_NODES
            );
        }
        if (!StringUtils.hasText(flowType) || TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT.equals(flowType)) {
            ensureDefaultTemplate(
                TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT,
                "新型号线标准流程",
                "审批中心默认新型号线流程模板，默认与新产品线节点一致",
                TimelineNodeConstants.MODEL_VARIANT_NODES
            );
        }
    }

    private void ensureDefaultTemplate(
        String flowType,
        String templateName,
        String description,
        List<TimelineNodeConstants.TimelineNodeDefinition> definitions
    ) {
        WorkflowTemplate active = findActiveTemplate(flowType);
        if (active != null) {
            if (nodes(active.getWorkflowTemplateId(), false).isEmpty()) {
                insertDefaultNodes(active.getWorkflowTemplateId(), definitions);
            }
            return;
        }
        WorkflowTemplate existing = first(templateRepository.selectList(new LambdaQueryWrapper<WorkflowTemplate>()
            .eq(WorkflowTemplate::getFlowType, flowType)
            .eq(WorkflowTemplate::getDeletedFlag, 0)
            .orderByAsc(WorkflowTemplate::getWorkflowTemplateId)));
        if (existing != null) {
            if (nodes(existing.getWorkflowTemplateId(), false).isEmpty()) {
                insertDefaultNodes(existing.getWorkflowTemplateId(), definitions);
            }
            existing.setTemplateName(StringUtils.hasText(existing.getTemplateName()) ? existing.getTemplateName() : templateName);
            existing.setVersionNo(StringUtils.hasText(existing.getVersionNo()) ? existing.getVersionNo() : "V1");
            existing.setStatus(STATUS_ACTIVE);
            existing.setActiveFlag(1);
            fillUpdateAudit(existing);
            templateRepository.updateById(existing);
            return;
        }
        WorkflowTemplate template = new WorkflowTemplate();
        template.setFlowType(flowType);
        template.setTemplateName(templateName);
        template.setVersionNo("V1");
        template.setStatus(STATUS_ACTIVE);
        template.setActiveFlag(1);
        template.setDescription(description);
        fillCreateAudit(template);
        templateRepository.insert(template);
        insertDefaultNodes(template.getWorkflowTemplateId(), definitions);
    }

    private void insertDefaultNodes(Long workflowTemplateId, List<TimelineNodeConstants.TimelineNodeDefinition> definitions) {
        for (TimelineNodeConstants.TimelineNodeDefinition definition : definitions) {
            WorkflowTemplateNode node = new WorkflowTemplateNode();
            node.setWorkflowTemplateId(workflowTemplateId);
            node.setStepNo(definition.stepNo());
            node.setNodeCode(definition.nodeCode());
            node.setNodeName(definition.nodeName());
            node.setStageCode(definition.stageCode());
            node.setStageName(definition.stageName());
            node.setPhaseName(definition.phaseName());
            node.setRequiredAttachment(Boolean.TRUE.equals(definition.requiredAttachment()) ? 1 : 0);
            node.setRequiredFileCategory(definition.requiredFileCategory());
            node.setUploadPrompt("请按节点要求上传资料，可补充版本号和备注。");
            node.setConfirmPrompt("确认前请检查必传资料、BOM、工艺或门禁条件是否完成。");
            node.setEmptyFileMessage("当前节点必传资料未上传：" + definition.nodeName());
            node.setGateFlag(Boolean.TRUE.equals(definition.gateFlag()) ? 1 : 0);
            node.setEnabledFlag(1);
            fillCreateAudit(node);
            nodeRepository.insert(node);
        }
    }

    private List<WorkflowTemplateNode> nodes(Long workflowTemplateId, boolean enabledOnly) {
        LambdaQueryWrapper<WorkflowTemplateNode> wrapper = new LambdaQueryWrapper<WorkflowTemplateNode>()
            .eq(WorkflowTemplateNode::getWorkflowTemplateId, workflowTemplateId)
            .eq(WorkflowTemplateNode::getDeletedFlag, 0)
            .eq(enabledOnly, WorkflowTemplateNode::getEnabledFlag, 1)
            .orderByAsc(WorkflowTemplateNode::getStepNo);
        return nodeRepository.selectList(wrapper);
    }

    private void replaceNodes(Long workflowTemplateId, List<WorkflowTemplateNodeSaveDTO> dtos) {
        LocalDateTime now = LocalDateTime.now();
        String operator = currentUserName();
        List<WorkflowTemplateNode> oldNodes = nodes(workflowTemplateId, false);
        for (WorkflowTemplateNode oldNode : oldNodes) {
            oldNode.setDeletedFlag(1);
            oldNode.setUpdatedAt(now);
            oldNode.setUpdatedBy(operator);
            nodeRepository.updateById(oldNode);
        }
        List<WorkflowTemplateNode> newNodes = new ArrayList<>();
        for (WorkflowTemplateNodeSaveDTO dto : dtos) {
            WorkflowTemplateNode node = new WorkflowTemplateNode();
            node.setWorkflowTemplateId(workflowTemplateId);
            node.setStepNo(dto.getStepNo());
            node.setNodeCode(cleanCode(dto.getNodeCode()));
            node.setNodeName(dto.getNodeName().trim());
            node.setStageCode(cleanNullable(dto.getStageCode()));
            node.setStageName(cleanNullable(dto.getStageName()));
            node.setPhaseName(cleanNullable(dto.getPhaseName()));
            node.setRequiredAttachment(Boolean.TRUE.equals(dto.getRequiredAttachment()) ? 1 : 0);
            node.setRequiredFileCategory(Boolean.TRUE.equals(dto.getRequiredAttachment()) ? cleanNullable(dto.getRequiredFileCategory()) : null);
            node.setUploadPrompt(cleanNullable(dto.getUploadPrompt()));
            node.setConfirmPrompt(cleanNullable(dto.getConfirmPrompt()));
            node.setEmptyFileMessage(cleanNullable(dto.getEmptyFileMessage()));
            node.setGateFlag(Boolean.TRUE.equals(dto.getGateFlag()) ? 1 : 0);
            node.setEnabledFlag(Boolean.FALSE.equals(dto.getEnabledFlag()) ? 0 : 1);
            node.setRemark(cleanNullable(dto.getRemark()));
            fillCreateAudit(node);
            newNodes.add(node);
        }
        validateStepContinuity(newNodes.stream().filter(node -> Integer.valueOf(1).equals(node.getEnabledFlag())).toList());
        for (WorkflowTemplateNode node : newNodes) {
            nodeRepository.insert(node);
        }
    }

    private void validateTemplate(WorkflowTemplateSaveDTO dto) {
        ensureFlowType(dto.getFlowType());
        if (!StringUtils.hasText(dto.getTemplateName())) {
            throw validation("模板名称不能为空");
        }
        if (dto.getNodes() == null || dto.getNodes().isEmpty()) {
            throw validation("流程模板至少需要一个节点");
        }
        Set<Integer> steps = new HashSet<>();
        Set<String> codes = new HashSet<>();
        for (WorkflowTemplateNodeSaveDTO node : dto.getNodes()) {
            if (node.getStepNo() == null || node.getStepNo() < 1) {
                throw validation("节点顺序必须从 1 开始");
            }
            if (!steps.add(node.getStepNo())) {
                throw validation("节点顺序不能重复：" + node.getStepNo());
            }
            String code = cleanCode(node.getNodeCode());
            if (!codes.add(code)) {
                throw validation("节点编码不能重复：" + code);
            }
            if (!StringUtils.hasText(node.getNodeName())) {
                throw validation("节点名称不能为空：" + code);
            }
            if (Boolean.TRUE.equals(node.getRequiredAttachment()) && !StringUtils.hasText(node.getRequiredFileCategory())) {
                throw validation("必传资料节点必须配置资料类别：" + node.getNodeName());
            }
        }
    }

    private void validateStepContinuity(List<WorkflowTemplateNode> nodes) {
        List<Integer> steps = nodes.stream()
            .map(WorkflowTemplateNode::getStepNo)
            .sorted()
            .toList();
        for (int index = 0; index < steps.size(); index++) {
            if (steps.get(index) != index + 1) {
                throw validation("启用节点顺序必须连续，从 1 开始");
            }
        }
    }

    private WorkflowTemplate getTemplateOrThrow(Long workflowTemplateId) {
        WorkflowTemplate template = templateRepository.selectById(workflowTemplateId);
        if (template == null || Integer.valueOf(1).equals(template.getDeletedFlag())) {
            throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "流程模板不存在");
        }
        return template;
    }

    private WorkflowTemplateNodeSaveDTO copyNode(WorkflowTemplateNode source) {
        WorkflowTemplateNodeSaveDTO node = new WorkflowTemplateNodeSaveDTO();
        node.setStepNo(source.getStepNo());
        node.setNodeCode(source.getNodeCode());
        node.setNodeName(source.getNodeName());
        node.setStageCode(source.getStageCode());
        node.setStageName(source.getStageName());
        node.setPhaseName(source.getPhaseName());
        node.setRequiredAttachment(Integer.valueOf(1).equals(source.getRequiredAttachment()));
        node.setRequiredFileCategory(source.getRequiredFileCategory());
        node.setUploadPrompt(source.getUploadPrompt());
        node.setConfirmPrompt(source.getConfirmPrompt());
        node.setEmptyFileMessage(source.getEmptyFileMessage());
        node.setGateFlag(Integer.valueOf(1).equals(source.getGateFlag()));
        node.setEnabledFlag(!Integer.valueOf(0).equals(source.getEnabledFlag()));
        node.setRemark(source.getRemark());
        return node;
    }

    private void ensureFlowType(String flowType) {
        if (!TimelineNodeConstants.PRODUCT_TYPE_PRODUCT_LINE.equals(flowType)
            && !TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT.equals(flowType)) {
            throw validation("只支持新产品线和新型号线流程");
        }
    }

    private String statusOrDraft(String status) {
        if (!StringUtils.hasText(status)) {
            return STATUS_DRAFT;
        }
        String clean = status.trim().toLowerCase(Locale.ROOT);
        if (STATUS_DRAFT.equals(clean) || STATUS_ACTIVE.equals(clean) || STATUS_INACTIVE.equals(clean)) {
            return clean;
        }
        throw validation("不支持的模板状态：" + status);
    }

    private String cleanCode(String value) {
        if (!StringUtils.hasText(value)) {
            throw validation("节点编码不能为空");
        }
        return value.trim().replaceAll("[^A-Za-z0-9_-]", "_").toUpperCase(Locale.ROOT);
    }

    private String cleanNullable(String value) {
        return StringUtils.hasText(value) ? value.trim() : null;
    }

    private String nextDraftVersion(String versionNo) {
        return StringUtils.hasText(versionNo) ? versionNo + "-copy" : "V1-copy";
    }

    private void fillCreateAudit(BaseEntity entity) {
        LocalDateTime now = LocalDateTime.now();
        String operator = currentUserName();
        entity.setCreatedAt(now);
        entity.setCreatedBy(operator);
        entity.setUpdatedAt(now);
        entity.setUpdatedBy(operator);
        entity.setDeletedFlag(0);
    }

    private void fillUpdateAudit(BaseEntity entity) {
        entity.setUpdatedAt(LocalDateTime.now());
        entity.setUpdatedBy(currentUserName());
    }

    private String currentUserName() {
        return CurrentUserContext.get()
            .map(CurrentUser::displayName)
            .filter(StringUtils::hasText)
            .orElse("system");
    }

    private void writeLog(String action, WorkflowTemplate template, String detailJson) {
        operationLogService.logSuccess(OperationLogCreateCommand.builder()
            .action(action)
            .businessType("WORKFLOW_TEMPLATE")
            .businessId(String.valueOf(template.getWorkflowTemplateId()))
            .businessCode(template.getFlowType())
            .businessName(template.getTemplateName())
            .detailJson(detailJson)
            .build());
    }

    private BusinessException validation(String message) {
        return new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, message);
    }

    private <T> T first(List<T> values) {
        return values == null || values.isEmpty() ? null : values.get(0);
    }
}
