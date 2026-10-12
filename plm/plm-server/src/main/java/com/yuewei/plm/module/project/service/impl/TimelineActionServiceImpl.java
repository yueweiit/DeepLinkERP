package com.yuewei.plm.module.project.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.constant.ProductStatusConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.common.security.CurrentUserContext;
import com.yuewei.plm.module.attachment.constant.AttachmentOwnerTypeConstants;
import com.yuewei.plm.module.attachment.entity.Attachment;
import com.yuewei.plm.module.attachment.repository.AttachmentRepository;
import com.yuewei.plm.module.bom.service.ProductionConfirmationService;
import com.yuewei.plm.module.integration.dingtalk.service.DingTalkProjectCompletionReturnService;
import com.yuewei.plm.module.operationlog.constant.OperationActionConstants;
import com.yuewei.plm.module.operationlog.service.OperationLogCreateCommand;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.project.constant.TimelineNodeConstants;
import com.yuewei.plm.module.order.service.ProjectOrderLifecycleSync;
import com.yuewei.plm.module.project.constant.TimelineNodeConstants.TimelineNodeDefinition;
import com.yuewei.plm.module.project.dto.TimelineActionDTO;
import com.yuewei.plm.module.project.service.TimelineActionService;
import com.yuewei.plm.module.project.service.TimelineDefinitionProvider;
import com.yuewei.plm.module.project.variant.entity.RequirementForm;
import com.yuewei.plm.module.project.variant.repository.RequirementFormRepository;
import com.yuewei.plm.module.project.vo.TimelineActionResultVO;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import jakarta.servlet.http.HttpServletRequest;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.util.StringUtils;

@Service
@RequiredArgsConstructor
@Slf4j
public class TimelineActionServiceImpl implements TimelineActionService {

    private static final String ACTION_CONFIRM = "confirm";
    private static final String ACTION_ADVANCE = "advance";
    private static final String ACTION_RETURN = "return";

    private final ProductRepository productRepository;
    private final AttachmentRepository attachmentRepository;
    private final TimelineDefinitionProvider timelineDefinitionProvider;
    private final OperationLogService operationLogService;
    private final ProductionConfirmationService productionConfirmationService;
    private final RequirementFormRepository requirementFormRepository;
    @Autowired(required = false)
    private ProjectOrderLifecycleSync projectOrderLifecycleSync;
    @Autowired(required = false)
    private DingTalkProjectCompletionReturnService dingTalkProjectCompletionReturnService;

    @Override
    @Transactional
    public TimelineActionResultVO confirm(Long projectId, String nodeKey, TimelineActionDTO dto, HttpServletRequest request) {
        Product product = getProductOrThrow(projectId);
        requireTimelineStarted(product);
        TimelineContext context = requireCurrentNode(product, nodeKey);
        CurrentUser currentUser = requireCurrentUser();
        String remark = dto == null ? null : dto.getRemark();
        boolean hasNextStep = context.currentStepNo() < context.definitions().size();
        TimelineNodeDefinition nextNode = hasNextStep
            ? context.definitions().get(context.currentStepNo())
            : context.current();
        boolean crossingStage = hasNextStep && !context.current().stageCode().equals(nextNode.stageCode());

        requireBusinessGate(projectId, nodeKey);
        List<String> documentWarnings = new ArrayList<>();
        documentWarnings.addAll(collectCurrentNodeAttachmentWarnings(product, context.current()));

        if (crossingStage) {
            documentWarnings.addAll(collectStageDocumentWarnings(product, context.current()));
        }

        applyTimelineAudit(product, currentUser, ACTION_CONFIRM, remark);
        if (hasNextStep) {
            product.setCurrentStepNo(nextNode.stepNo());
            product.setTimelineCurrentConfirmed(false);
            product.setTimelineConfirmedNodeKey(null);
            product.setStatus(resolveProductStatus(nextNode.stepNo(), context.definitions().size()));
        } else {
            product.setCurrentStepNo(context.currentStepNo());
            product.setTimelineCurrentConfirmed(true);
            product.setTimelineConfirmedNodeKey(nodeKey);
            product.setStatus(resolveProductStatus(context.currentStepNo(), context.definitions().size()));
            completeModelVariantAtMoldTransfer(product, context.current(), currentUser);
            completeProductLineAtFinalStep(product, context.current(), currentUser);
        }
        productRepository.updateById(product);
        if (projectOrderLifecycleSync != null && product.getCurrentStepNo() != null && product.getCurrentStepNo() > 1) {
            projectOrderLifecycleSync.inProduction(projectId, currentUser.displayName());
        }

        Long logId = writeLog(
            product,
            OperationActionConstants.TIMELINE_CONFIRM,
            detailJsonForConfirmStep(product, context.current(), nextNode, hasNextStep, remark, documentWarnings),
            request
        );
        if (!hasNextStep) {
            triggerDingTalkCompletionReturn(product, context.current(), currentUser.displayName());
        }
        return buildResult(product, ACTION_CONFIRM, nodeKey, context.currentStepNo(), nextNode, !hasNextStep, logId, documentWarnings);
    }

    private void requireBusinessGate(Long projectId, String nodeKey) {
        switch (nodeKey) {
            case "PRODUCT_LINE_PROCESS_PLAN", "MODEL_VARIANT_PROCESS_PLAN" ->
                productionConfirmationService.requireBomRoutesDetermined(projectId);
            case "PRODUCT_LINE_PROCESS_CONFIRM", "MODEL_VARIANT_PROCESS_CONFIRM" ->
                productionConfirmationService.requireOperationsConfirmed(projectId);
            case "PRODUCT_LINE_PRODUCTION_DECISION_STEP", "MODEL_VARIANT_MOLD_TRANSFER" ->
                productionConfirmationService.requireColorsConfirmed(projectId);
            default -> {
                // Other timeline nodes keep their existing document and status gates.
            }
        }
    }

    private List<String> collectCurrentNodeAttachmentWarnings(Product product, TimelineNodeDefinition currentNode) {
        if (!StringUtils.hasText(currentNode.requiredFileCategory())) {
            return List.of();
        }
        Long count = attachmentRepository.selectCount(new LambdaQueryWrapper<Attachment>()
            .eq(Attachment::getOwnerObjectType, AttachmentOwnerTypeConstants.PRODUCT)
            .eq(Attachment::getOwnerObjectId, product.getProductId())
            .eq(Attachment::getTimelineNodeKey, currentNode.nodeCode())
            .eq(Attachment::getFileCategory, currentNode.requiredFileCategory())
            .eq(Attachment::getDeletedFlag, 0));
        if (count == null || count == 0) {
            return List.of(
                StringUtils.hasText(currentNode.emptyFileMessage())
                    ? currentNode.emptyFileMessage()
                    : "当前步骤资料未上传：" + currentNode.nodeName()
            );
        }
        return List.of();
    }

    @Override
    @Transactional
    public TimelineActionResultVO advance(Long projectId, String nodeKey, TimelineActionDTO dto, HttpServletRequest request) {
        Product product = getProductOrThrow(projectId);
        requireTimelineStarted(product);
        TimelineContext context = requireCurrentNode(product, nodeKey);
        if (context.currentStepNo() >= context.definitions().size()) {
            throw new BusinessException(ErrorCodeConstants.STATUS_TRANSITION_ILLEGAL, "最后节点不能继续推进");
        }
        if (!Boolean.TRUE.equals(product.getTimelineCurrentConfirmed()) || !nodeKey.equals(product.getTimelineConfirmedNodeKey())) {
            throw new BusinessException(ErrorCodeConstants.STATUS_TRANSITION_ILLEGAL, "当前节点尚未确认，不能推进");
        }
        CurrentUser currentUser = requireCurrentUser();
        String remark = dto == null ? null : dto.getRemark();
        int nextStepNo = context.currentStepNo() + 1;
        TimelineNodeDefinition nextNode = context.definitions().get(nextStepNo - 1);

        product.setCurrentStepNo(nextStepNo);
        product.setTimelineCurrentConfirmed(false);
        product.setTimelineConfirmedNodeKey(null);
        product.setStatus(resolveProductStatus(nextStepNo, context.definitions().size()));
        applyTimelineAudit(product, currentUser, ACTION_ADVANCE, remark);
        productRepository.updateById(product);
        if (projectOrderLifecycleSync != null) projectOrderLifecycleSync.inProduction(projectId, currentUser.displayName());

        Long logId = writeLog(
            product,
            OperationActionConstants.TIMELINE_ADVANCE,
            detailJsonForMove(product, ACTION_ADVANCE, context.current(), nextNode, true, remark),
            request
        );
        return buildResult(product, ACTION_ADVANCE, nodeKey, context.currentStepNo(), nextNode, false, logId, List.of());
    }

    @Override
    @Transactional
    public TimelineActionResultVO returnNode(Long projectId, String nodeKey, TimelineActionDTO dto, HttpServletRequest request) {
        Product product = getProductOrThrow(projectId);
        requireTimelineStarted(product);
        TimelineContext context = requireCurrentNode(product, nodeKey);
        String reason = dto == null ? null : dto.getReason();
        if (!StringUtils.hasText(reason)) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "退回原因不能为空");
        }
        boolean returnToPrevious = Boolean.TRUE.equals(dto.getReturnToPrevious());
        if (returnToPrevious && context.currentStepNo() <= 1) {
            throw new BusinessException(ErrorCodeConstants.STATUS_TRANSITION_ILLEGAL, "第一个节点不能退回上一节点");
        }
        CurrentUser currentUser = requireCurrentUser();
        int targetStepNo = returnToPrevious ? context.currentStepNo() - 1 : context.currentStepNo();
        TimelineNodeDefinition targetNode = context.definitions().get(targetStepNo - 1);

        product.setCurrentStepNo(targetStepNo);
        product.setTimelineCurrentConfirmed(false);
        product.setTimelineConfirmedNodeKey(null);
        product.setStatus(resolveProductStatus(targetStepNo, context.definitions().size()));
        applyTimelineAudit(product, currentUser, ACTION_RETURN, reason);
        productRepository.updateById(product);

        Long logId = writeLog(
            product,
            OperationActionConstants.TIMELINE_RETURN,
            detailJsonForMove(product, ACTION_RETURN, context.current(), targetNode, returnToPrevious, reason),
            request
        );
        return buildResult(product, ACTION_RETURN, nodeKey, context.currentStepNo(), targetNode, false, logId, List.of());
    }

    private Product getProductOrThrow(Long projectId) {
        Product product = productRepository.selectById(projectId);
        if (product == null || Integer.valueOf(1).equals(product.getDeletedFlag())) {
            throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "项目不存在");
        }
        return product;
    }

    private void requireTimelineStarted(Product product) {
        if (!TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT.equals(product.getProductType())) {
            return;
        }
        RequirementForm form = requirementFormRepository.selectList(new LambdaQueryWrapper<RequirementForm>()
                .eq(RequirementForm::getProjectId, product.getProductId())
                .eq(RequirementForm::getDeletedFlag, 0))
            .stream()
            .findFirst()
            .orElse(null);
        if (form == null || !"confirmed".equals(form.getStatus())) {
            throw new BusinessException(
                ErrorCodeConstants.STATUS_TRANSITION_ILLEGAL,
                "请先完成新型号项目信息完善表，确认后才能操作项目时间轴"
            );
        }
    }

    private TimelineContext requireCurrentNode(Product product, String nodeKey) {
        List<TimelineNodeDefinition> definitions = timelineDefinitionProvider.getDefinitions(product);
        int currentStepNo = normalizeStepNo(product.getCurrentStepNo(), definitions.size());
        TimelineNodeDefinition current = definitions.get(currentStepNo - 1);
        if (!current.nodeCode().equals(nodeKey)) {
            throw new BusinessException(ErrorCodeConstants.STATUS_TRANSITION_ILLEGAL, "只能操作当前时间轴节点");
        }
        return new TimelineContext(definitions, currentStepNo, current);
    }

    private int normalizeStepNo(Integer currentStepNo, int maxStepNo) {
        if (currentStepNo == null || currentStepNo < 1) {
            return 1;
        }
        return Math.min(currentStepNo, maxStepNo);
    }

    private List<String> collectStageDocumentWarnings(Product product, TimelineNodeDefinition currentNode) {
        List<TimelineNodeDefinition> requiredDefinitions = timelineDefinitionProvider.getRequiredDefinitionsForStage(
            product,
            currentNode.stageCode()
        );
        if (requiredDefinitions.isEmpty()) {
            return List.of();
        }
        Set<String> uploadedNodeKeys = attachmentRepository.selectList(new LambdaQueryWrapper<Attachment>()
                .eq(Attachment::getOwnerObjectType, AttachmentOwnerTypeConstants.PRODUCT)
                .eq(Attachment::getOwnerObjectId, product.getProductId())
                .eq(Attachment::getDeletedFlag, 0))
            .stream()
            .map(Attachment::getTimelineNodeKey)
            .filter(StringUtils::hasText)
            .collect(Collectors.toSet());

        List<String> missing = requiredDefinitions.stream()
            .filter(definition -> !uploadedNodeKeys.contains(definition.nodeCode()))
            .map(TimelineNodeDefinition::nodeCode)
            .toList();
        if (!missing.isEmpty()) {
            return List.of("当前阶段资料未齐全：" + String.join(",", missing));
        }
        return List.of();
    }

    private CurrentUser requireCurrentUser() {
        return CurrentUserContext.get()
            .orElseThrow(() -> new BusinessException(ErrorCodeConstants.UNAUTHORIZED, "未登录或登录已失效"));
    }

    private void applyTimelineAudit(Product product, CurrentUser currentUser, String action, String reason) {
        LocalDateTime now = LocalDateTime.now();
        product.setTimelineLastAction(action);
        product.setTimelineLastReason(reason);
        product.setTimelineLastOperatedAt(now);
        product.setTimelineLastOperatorUserId(currentUser.userId());
        product.setTimelineLastOperatorUserName(currentUser.displayName());
        product.setUpdatedAt(now);
        product.setUpdatedBy(currentUser.displayName());
    }

    private String resolveProductStatus(int stepNo, int maxStepNo) {
        if (stepNo <= 1) {
            return ProductStatusConstants.DRAFT;
        }
        if (stepNo >= maxStepNo) {
            return ProductStatusConstants.RELEASED;
        }
        return ProductStatusConstants.DEVELOPING;
    }

    private void completeModelVariantAtMoldTransfer(Product product, TimelineNodeDefinition currentNode, CurrentUser currentUser) {
        if (!TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT.equals(product.getProductType())
            || !"MODEL_VARIANT_MOLD_TRANSFER".equals(currentNode.nodeCode())) {
            return;
        }
        productionConfirmationService.syncModelVariantConfirmedColorsAndSkus(product);
        LocalDateTime now = LocalDateTime.now();
        if (product.getMoldTransferAt() == null) {
            product.setMoldTransferAt(now);
        }
        product.setStatus(ProductStatusConstants.RELEASED);
        product.setReleasedAt(now);
        product.setReleasedBy(currentUser.displayName());
        product.setUpdatedAt(now);
        product.setUpdatedBy(currentUser.displayName());
    }

    private void completeProductLineAtFinalStep(Product product, TimelineNodeDefinition currentNode, CurrentUser currentUser) {
        if (!TimelineNodeConstants.PRODUCT_TYPE_PRODUCT_LINE.equals(product.getProductType())
            || !"PRODUCT_LINE_PRODUCTION_DECISION_STEP".equals(currentNode.nodeCode())) {
            return;
        }
        LocalDateTime now = LocalDateTime.now();
        product.setStatus(ProductStatusConstants.RELEASED);
        product.setReleasedAt(now);
        product.setReleasedBy(currentUser.displayName());
        product.setUpdatedAt(now);
        product.setUpdatedBy(currentUser.displayName());
    }

    private void triggerDingTalkCompletionReturn(Product product, TimelineNodeDefinition currentNode, String operator) {
        if (dingTalkProjectCompletionReturnService == null) {
            return;
        }
        Runnable task = () -> {
            try {
                dingTalkProjectCompletionReturnService.handleProjectCompleted(product, currentNode, operator);
            } catch (Exception ex) {
                log.warn(
                    "DingTalk project completion return failed after PLM timeline completion, projectId={}, nodeKey={}",
                    product.getProductId(),
                    currentNode.nodeCode(),
                    ex
                );
            }
        };
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    task.run();
                }
            });
            return;
        }
        task.run();
    }

    private Long writeLog(Product product, String action, String detailJson, HttpServletRequest request) {
        return operationLogService.logSuccess(OperationLogCreateCommand.builder()
            .action(action)
            .businessType("PRODUCT")
            .businessId(String.valueOf(product.getProductId()))
            .businessCode(product.getProductCode())
            .businessName(product.getProductName())
            .detailJson(detailJson)
            .request(request)
            .build());
    }

    private TimelineActionResultVO buildResult(
        Product product,
        String action,
        String nodeKey,
        Integer beforeStepNo,
        TimelineNodeDefinition currentNode,
        Boolean currentConfirmed,
        Long logId,
        List<String> warnings
    ) {
        String currentNodeName = currentNode.nodeName();
        return TimelineActionResultVO.builder()
            .projectId(product.getProductId())
            .productId(product.getProductId())
            .action(action)
            .nodeKey(nodeKey)
            .beforeStepNo(beforeStepNo)
            .currentStepNo(product.getCurrentStepNo())
            .currentNodeKey(currentNode.nodeCode())
            .currentNodeName(currentNodeName)
            .currentConfirmed(currentConfirmed)
            .productStatus(product.getStatus())
            .logId(logId)
            .warnings(warnings)
            .build();
    }

    private String detailJsonForConfirmStep(
        Product product,
        TimelineNodeDefinition fromNode,
        TimelineNodeDefinition toNode,
        boolean moved,
        String remark,
        List<String> warnings
    ) {
        return "{"
            + "\"projectId\":" + product.getProductId()
            + ",\"productId\":" + product.getProductId()
            + ",\"action\":\"confirm\""
            + ",\"fromNodeKey\":\"" + json(fromNode.nodeCode()) + "\""
            + ",\"fromStepNo\":" + fromNode.stepNo()
            + ",\"toNodeKey\":\"" + json(toNode.nodeCode()) + "\""
            + ",\"toStepNo\":" + toNode.stepNo()
            + ",\"moved\":" + moved
            + ",\"remark\":\"" + json(remark) + "\""
            + ",\"documentWarnings\":" + jsonArray(warnings)
            + "}";
    }

    private String detailJsonForMove(
        Product product,
        String action,
        TimelineNodeDefinition fromNode,
        TimelineNodeDefinition toNode,
        boolean returnToPrevious,
        String reasonOrRemark
    ) {
        String valueName = ACTION_RETURN.equals(action) ? "reason" : "remark";
        return "{"
            + "\"projectId\":" + product.getProductId()
            + ",\"productId\":" + product.getProductId()
            + ",\"action\":\"" + action + "\""
            + ",\"fromNodeKey\":\"" + json(fromNode.nodeCode()) + "\""
            + ",\"fromStepNo\":" + fromNode.stepNo()
            + ",\"toNodeKey\":\"" + json(toNode.nodeCode()) + "\""
            + ",\"toStepNo\":" + toNode.stepNo()
            + ",\"returnToPrevious\":" + returnToPrevious
            + ",\"" + valueName + "\":\"" + json(reasonOrRemark) + "\""
            + "}";
    }

    private String json(String value) {
        if (value == null) {
            return "";
        }
        return value.replace("\\", "\\\\").replace("\"", "\\\"");
    }

    private String jsonArray(List<String> values) {
        if (values == null || values.isEmpty()) {
            return "[]";
        }
        return "[" + values.stream().map(value -> "\"" + json(value) + "\"").collect(Collectors.joining(",")) + "]";
    }

    private record TimelineContext(
        List<TimelineNodeDefinition> definitions,
        int currentStepNo,
        TimelineNodeDefinition current
    ) {
    }
}
