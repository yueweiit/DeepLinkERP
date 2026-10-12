package com.yuewei.plm.module.integration.dingtalk.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.module.integration.dingtalk.config.DingTalkIntegrationProperties;
import com.yuewei.plm.module.integration.dingtalk.entity.IntegrationRecord;
import com.yuewei.plm.module.integration.dingtalk.repository.IntegrationRecordRepository;
import com.yuewei.plm.module.integration.dingtalk.service.DingTalkOutboundApprovalClient.DingTalkOutboundResult;
import com.yuewei.plm.module.integration.dingtalk.vo.DingTalkOutboundTriggerResultVO;
import com.yuewei.plm.module.operationlog.constant.OperationActionConstants;
import com.yuewei.plm.module.operationlog.service.OperationLogCreateCommand;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.project.constant.TimelineNodeConstants;
import com.yuewei.plm.module.project.constant.TimelineNodeConstants.TimelineNodeDefinition;
import com.yuewei.plm.repository.entity.BaseEntity;
import com.yuewei.plm.repository.entity.Product;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

@Service
@RequiredArgsConstructor
public class DingTalkProjectCompletionReturnService {
    private static final String SOURCE_SYSTEM = "dingtalk";
    private static final String DIRECTION_INBOUND = "inbound";
    private static final String DIRECTION_OUTBOUND = "outbound";
    private static final String PROCESSING_SUCCESS = "success";
    private static final String PROCESSING_FAILED = "failed";
    private static final String MODEL_VARIANT_INBOUND_TYPE = "model_variant";
    private static final String MODEL_VARIANT_OUTBOUND_TYPE = "model_variant_mold_transfer_completed";
    private static final String PRODUCT_LINE_INBOUND_TYPE = "product_line";
    private static final String PRODUCT_LINE_OUTBOUND_TYPE = "product_line_completed_cc";
    private static final String MODEL_VARIANT_FINAL_NODE = "MODEL_VARIANT_MOLD_TRANSFER";
    private static final String PRODUCT_LINE_FINAL_NODE = "PRODUCT_LINE_PRODUCTION_DECISION_STEP";

    private final IntegrationRecordRepository integrationRepository;
    private final DingTalkOutboundApprovalClient outboundClient;
    private final DingTalkIntegrationProperties properties;
    private final ObjectMapper objectMapper;
    private final OperationLogService operationLogService;

    @Transactional
    public DingTalkOutboundTriggerResultVO handleProjectCompleted(
        Product product,
        TimelineNodeDefinition node,
        String operator
    ) {
        if (product == null || node == null) {
            return null;
        }
        if (TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT.equals(product.getProductType())
            && MODEL_VARIANT_FINAL_NODE.equals(node.nodeCode())) {
            return autoAgreeModelVariant(product, node, operator);
        }
        if (TimelineNodeConstants.PRODUCT_TYPE_PRODUCT_LINE.equals(product.getProductType())
            && PRODUCT_LINE_FINAL_NODE.equals(node.nodeCode())) {
            return notifyProductLineCompleted(product, node, operator);
        }
        return null;
    }

    private DingTalkOutboundTriggerResultVO autoAgreeModelVariant(
        Product product,
        TimelineNodeDefinition node,
        String operator
    ) {
        IntegrationRecord inbound = inbound(product, MODEL_VARIANT_INBOUND_TYPE);
        IntegrationRecord existing = outbound(product, node, MODEL_VARIANT_OUTBOUND_TYPE);
        if (existing != null && PROCESSING_SUCCESS.equals(existing.getProcessingStatus())) {
            return toResult(existing, true);
        }

        Map<String, Object> payload = inbound == null
            ? missingInboundPayload(product, node, "agree", MODEL_VARIANT_INBOUND_TYPE)
            : modelVariantAgreePayload(product, node, inbound);
        String errorMessage = inbound == null ? "未找到钉钉新型号入站记录，无法自动代同意" : null;
        DingTalkOutboundResult result = null;
        if (errorMessage == null && !StringUtils.hasText(text(payload.get("taskId")))) {
            TaskLookupAttempt lookup = lookupWorkflowTask(product, node, inbound);
            if (StringUtils.hasText(lookup.errorMessage())) {
                payload.put("taskLookupError", lookup.errorMessage());
            }
            if (StringUtils.hasText(lookup.taskId())) {
                payload.put("taskId", lookup.taskId());
                payload.put("taskIdSource", "lookup");
            } else {
                errorMessage = "钉钉等待节点 taskId 未保存，且兜底查询未返回 taskId，无法自动代同意";
            }
        }
        if (errorMessage == null && !StringUtils.hasText(text(payload.get("taskId")))) {
            errorMessage = "钉钉等待节点 taskId 未保存，无法自动代同意";
        }
        if (errorMessage == null && !StringUtils.hasText(properties.getAutoApproverUserId())) {
            errorMessage = "钉钉自动审批人 userId 未配置";
        }
        if (errorMessage == null) {
            try {
                result = outboundClient.executeWorkflowTask(payload);
                if (isFailedOutbound(result)) {
                    errorMessage = "DingTalk outbound relay returned failed: " + result.rawPayloadJson();
                }
            } catch (Exception ex) {
                errorMessage = ex.getMessage();
            }
        }
        IntegrationRecord record = saveOutbound(
            existing,
            product,
            node,
            inbound,
            MODEL_VARIANT_OUTBOUND_TYPE,
            properties.getModelVariantProcessCode(),
            payload,
            result,
            errorMessage,
            operator
        );
        writeLog(product, node, "dingtalk_model_variant_auto_agree", record);
        return toResult(record, false);
    }

    private DingTalkOutboundTriggerResultVO notifyProductLineCompleted(
        Product product,
        TimelineNodeDefinition node,
        String operator
    ) {
        IntegrationRecord inbound = inbound(product, PRODUCT_LINE_INBOUND_TYPE);
        IntegrationRecord existing = outbound(product, node, PRODUCT_LINE_OUTBOUND_TYPE);
        if (existing != null && PROCESSING_SUCCESS.equals(existing.getProcessingStatus())) {
            return toResult(existing, true);
        }

        Map<String, Object> payload = inbound == null
            ? missingInboundPayload(product, node, "cc", PRODUCT_LINE_INBOUND_TYPE)
            : productLineCcPayload(product, node, inbound);
        String errorMessage = inbound == null ? "未找到钉钉新产品线入站记录，无法发送完成抄送" : null;
        DingTalkOutboundResult result = null;
        if (errorMessage == null && (properties.getProductLineCcUserIds() == null || properties.getProductLineCcUserIds().isEmpty())) {
            errorMessage = "钉钉新产品线完成抄送人未配置";
        } else if (errorMessage == null) {
            try {
                result = outboundClient.sendCompletionNotice(payload);
                if (isFailedOutbound(result)) {
                    errorMessage = "DingTalk outbound relay returned failed: " + result.rawPayloadJson();
                }
            } catch (Exception ex) {
                errorMessage = ex.getMessage();
            }
        }
        IntegrationRecord record = saveOutbound(
            existing,
            product,
            node,
            inbound,
            PRODUCT_LINE_OUTBOUND_TYPE,
            properties.getProductLineProcessCode(),
            payload,
            result,
            errorMessage,
            operator
        );
        writeLog(product, node, "dingtalk_product_line_completed_cc", record);
        return toResult(record, false);
    }

    private IntegrationRecord inbound(Product product, String integrationType) {
        return first(integrationRepository.selectList(new LambdaQueryWrapper<IntegrationRecord>()
            .eq(IntegrationRecord::getSourceSystem, SOURCE_SYSTEM)
            .eq(IntegrationRecord::getIntegrationType, integrationType)
            .eq(IntegrationRecord::getProjectId, product.getProductId())
            .eq(IntegrationRecord::getDirection, DIRECTION_INBOUND)
            .eq(IntegrationRecord::getDeletedFlag, 0)));
    }

    private IntegrationRecord outbound(Product product, TimelineNodeDefinition node, String integrationType) {
        List<IntegrationRecord> records = integrationRepository.selectList(new LambdaQueryWrapper<IntegrationRecord>()
            .eq(IntegrationRecord::getSourceSystem, SOURCE_SYSTEM)
            .eq(IntegrationRecord::getIntegrationType, integrationType)
            .eq(IntegrationRecord::getProjectId, product.getProductId())
            .eq(IntegrationRecord::getNodeKey, node.nodeCode())
            .eq(IntegrationRecord::getDirection, DIRECTION_OUTBOUND)
            .eq(IntegrationRecord::getDeletedFlag, 0));
        if (records == null || records.isEmpty()) {
            return null;
        }
        return records.stream()
            .filter(record -> PROCESSING_SUCCESS.equals(record.getProcessingStatus()))
            .findFirst()
            .orElse(first(records));
    }

    private Map<String, Object> modelVariantAgreePayload(
        Product product,
        TimelineNodeDefinition node,
        IntegrationRecord inbound
    ) {
        Map<String, Object> payload = basePayload(product, node, inbound, "agree");
        payload.put("processCode", properties.getModelVariantProcessCode());
        payload.put("processInstanceId", inbound.getExternalInstanceId());
        payload.put("approvalInstanceId", inbound.getExternalInstanceId());
        payload.put("taskId", taskId(inbound));
        payload.put("actionerUserId", properties.getAutoApproverUserId());
        payload.put("result", "agree");
        payload.put("remark", "PLM 运模已完成，项目已归档，自动代同意钉钉等待节点");
        return payload;
    }

    private TaskLookupAttempt lookupWorkflowTask(
        Product product,
        TimelineNodeDefinition node,
        IntegrationRecord inbound
    ) {
        Map<String, Object> payload = basePayload(product, node, inbound, "workflow-task-lookup");
        payload.put("processCode", properties.getModelVariantProcessCode());
        payload.put("processInstanceId", inbound.getExternalInstanceId());
        payload.put("approvalInstanceId", inbound.getExternalInstanceId());
        payload.put("actionerUserId", properties.getAutoApproverUserId());
        try {
            String taskId = outboundClient.lookupWorkflowTask(payload);
            return new TaskLookupAttempt(taskId, null);
        } catch (Exception ex) {
            return new TaskLookupAttempt(null, ex.getMessage());
        }
    }

    private Map<String, Object> productLineCcPayload(
        Product product,
        TimelineNodeDefinition node,
        IntegrationRecord inbound
    ) {
        Map<String, Object> payload = basePayload(product, node, inbound, "cc");
        payload.put("processCode", properties.getProductLineProcessCode());
        payload.put("processInstanceId", inbound.getExternalInstanceId());
        payload.put("approvalInstanceId", inbound.getExternalInstanceId());
        payload.put("receiverUserIds", properties.getProductLineCcUserIds());
        payload.put("title", "PLM 新产品线流程已完成");
        payload.put("content", "PLM 新产品线流程已完成：" + nullToEmpty(product.getProductName()));
        return payload;
    }

    private Map<String, Object> missingInboundPayload(
        Product product,
        TimelineNodeDefinition node,
        String action,
        String inboundIntegrationType
    ) {
        Map<String, Object> payload = basePayload(product, node, null, action);
        payload.put("missingInboundIntegrationType", inboundIntegrationType);
        return payload;
    }

    private Map<String, Object> basePayload(
        Product product,
        TimelineNodeDefinition node,
        IntegrationRecord inbound,
        String action
    ) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("action", action);
        payload.put("projectId", product.getProductId());
        payload.put("projectCode", product.getProductCode());
        payload.put("projectName", product.getProductName());
        payload.put("productType", product.getProductType());
        payload.put("model", product.getModel());
        payload.put("nodeKey", node.nodeCode());
        payload.put("nodeName", node.nodeName());
        payload.put("sourceApprovalInstanceId", inbound == null ? null : inbound.getExternalInstanceId());
        payload.put("completedAt", LocalDateTime.now().toString());
        return payload;
    }

    private IntegrationRecord saveOutbound(
        IntegrationRecord existing,
        Product product,
        TimelineNodeDefinition node,
        IntegrationRecord inbound,
        String integrationType,
        String processCode,
        Map<String, Object> payload,
        DingTalkOutboundResult result,
        String errorMessage,
        String operator
    ) {
        IntegrationRecord record = existing == null ? new IntegrationRecord() : existing;
        String effectiveErrorMessage = effectiveErrorMessage(errorMessage, payload);
        record.setSourceSystem(SOURCE_SYSTEM);
        record.setIntegrationType(integrationType);
        record.setExternalInstanceId(resolveExternalInstanceId(result, inbound));
        record.setExternalStatus(resolveExternalStatus(result, effectiveErrorMessage));
        record.setProcessCode(processCode);
        record.setDirection(DIRECTION_OUTBOUND);
        record.setNodeKey(node.nodeCode());
        record.setExternalUrl(result == null ? null : result.externalUrl());
        record.setSourcePayloadJson(toJson(payload));
        record.setProcessingStatus(effectiveErrorMessage == null ? PROCESSING_SUCCESS : PROCESSING_FAILED);
        record.setProjectId(product.getProductId());
        record.setErrorCode(effectiveErrorMessage == null ? null : "DINGTALK_PROJECT_COMPLETION_RETURN_FAILED");
        record.setErrorMessage(effectiveErrorMessage);
        record.setRetryCount(record.getRetryCount() == null ? 1 : record.getRetryCount() + 1);
        record.setLastTriggeredAt(LocalDateTime.now());
        if (existing == null) {
            fillCreate(record, operator);
            integrationRepository.insert(record);
        } else {
            fillUpdate(record, operator);
            integrationRepository.updateById(record);
        }
        return record;
    }

    private String resolveExternalStatus(DingTalkOutboundResult result, String errorMessage) {
        if (result != null && StringUtils.hasText(result.externalStatus())) {
            return result.externalStatus();
        }
        return StringUtils.hasText(errorMessage) ? PROCESSING_FAILED : PROCESSING_SUCCESS;
    }

    private boolean isFailedOutbound(DingTalkOutboundResult result) {
        return result != null && PROCESSING_FAILED.equalsIgnoreCase(result.externalStatus());
    }

    private String effectiveErrorMessage(String errorMessage, Map<String, Object> payload) {
        if (!StringUtils.hasText(errorMessage)) {
            return null;
        }
        String lookupError = text(payload == null ? null : payload.get("taskLookupError"));
        if (!StringUtils.hasText(lookupError) || errorMessage.contains(lookupError)) {
            return errorMessage;
        }
        return errorMessage + " (" + lookupError + ")";
    }

    private String resolveExternalInstanceId(DingTalkOutboundResult result, IntegrationRecord inbound) {
        if (inbound != null && StringUtils.hasText(inbound.getExternalInstanceId())) {
            return inbound.getExternalInstanceId();
        }
        if (result != null && StringUtils.hasText(result.externalInstanceId())) {
            return result.externalInstanceId();
        }
        return null;
    }

    private String taskId(IntegrationRecord inbound) {
        Map<String, Object> payload = fromJson(inbound.getSourcePayloadJson());
        String taskId = text(payload.get("taskId"));
        if (StringUtils.hasText(taskId)) return taskId;
        taskId = text(payload.get("approvalTaskId"));
        if (StringUtils.hasText(taskId)) return taskId;
        taskId = text(payload.get("task_id"));
        if (StringUtils.hasText(taskId)) return taskId;
        Object form = payload.get("form");
        if (form instanceof Map<?, ?> formMap) {
            taskId = text(formMap.get("taskId"));
            if (StringUtils.hasText(taskId)) return taskId;
            taskId = text(formMap.get("approvalTaskId"));
            if (StringUtils.hasText(taskId)) return taskId;
            return text(formMap.get("审批任务ID"));
        }
        return null;
    }

    private Map<String, Object> fromJson(String json) {
        if (!StringUtils.hasText(json)) {
            return Map.of();
        }
        try {
            return objectMapper.readValue(json, new TypeReference<Map<String, Object>>() {});
        } catch (Exception ignored) {
            return Map.of();
        }
    }

    private String toJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception ignored) {
            return null;
        }
    }

    private DingTalkOutboundTriggerResultVO toResult(IntegrationRecord record, boolean hit) {
        return DingTalkOutboundTriggerResultVO.builder()
            .integrationRecordId(record.getIntegrationRecordId())
            .projectId(record.getProjectId())
            .nodeKey(record.getNodeKey())
            .externalInstanceId(record.getExternalInstanceId())
            .externalUrl(record.getExternalUrl())
            .status(record.getProcessingStatus())
            .idempotentHit(hit)
            .build();
    }

    private void writeLog(Product product, TimelineNodeDefinition node, String action, IntegrationRecord record) {
        operationLogService.logSuccess(OperationLogCreateCommand.builder()
            .action(OperationActionConstants.DINGTALK_PROJECT_COMPLETION_RETURN)
            .businessType("PRODUCT")
            .businessId(String.valueOf(product.getProductId()))
            .businessCode(product.getProductCode())
            .businessName(product.getProductName())
            .detailJson("{\"action\":\"" + action + "\",\"nodeKey\":\"" + node.nodeCode()
                + "\",\"processingStatus\":\"" + record.getProcessingStatus() + "\"}")
            .build());
    }

    private void fillCreate(BaseEntity entity, String operator) {
        LocalDateTime now = LocalDateTime.now();
        entity.setCreatedAt(now);
        entity.setCreatedBy(StringUtils.hasText(operator) ? operator : "system");
        entity.setUpdatedAt(now);
        entity.setUpdatedBy(StringUtils.hasText(operator) ? operator : "system");
        entity.setDeletedFlag(0);
    }

    private void fillUpdate(BaseEntity entity, String operator) {
        entity.setUpdatedAt(LocalDateTime.now());
        entity.setUpdatedBy(StringUtils.hasText(operator) ? operator : "system");
    }

    private String text(Object value) {
        return value == null ? null : String.valueOf(value).trim();
    }

    private String nullToEmpty(String value) {
        return value == null ? "" : value;
    }

    private <T> T first(List<T> values) {
        return values == null || values.isEmpty() ? null : values.get(0);
    }

    private record TaskLookupAttempt(String taskId, String errorMessage) {}
}
