package com.yuewei.plm.module.integration.dingtalk.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
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
import com.yuewei.plm.module.project.entity.ProjectMoldTransferExpress;
import com.yuewei.plm.module.project.repository.ProjectMoldTransferExpressRepository;
import com.yuewei.plm.module.project.variant.entity.RequirementForm;
import com.yuewei.plm.module.project.variant.repository.RequirementFormRepository;
import com.yuewei.plm.repository.entity.BaseEntity;
import com.yuewei.plm.repository.entity.Product;
import com.yuewei.plm.repository.ProductRepository;
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
public class DingTalkShipMoldTriggerService {
    private static final String SOURCE_SYSTEM = "dingtalk";
    private static final String INBOUND_TYPE = "model_variant";
    private static final String OUTBOUND_TYPE = "model_variant_ship_mold";
    private static final String DIRECTION_OUTBOUND = "outbound";
    private static final String PROCESSING_SUCCESS = "success";

    private final IntegrationRecordRepository integrationRepository;
    private final RequirementFormRepository requirementFormRepository;
    private final ProjectMoldTransferExpressRepository moldTransferExpressRepository;
    private final ProductRepository productRepository;
    private final DingTalkOutboundApprovalClient outboundClient;
    private final DingTalkIntegrationProperties properties;
    private final OperationLogService operationLogService;

    @Transactional
    public DingTalkOutboundTriggerResultVO triggerIfNeeded(Product product, TimelineNodeDefinition node, String operator) {
        if (!TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT.equals(product.getProductType())) {
            return null;
        }
        if (!"MODEL_VARIANT_MOLD_TRANSFER".equals(node.nodeCode())) {
            return null;
        }
        IntegrationRecord inbound = first(integrationRepository.selectList(new LambdaQueryWrapper<IntegrationRecord>()
            .eq(IntegrationRecord::getSourceSystem, SOURCE_SYSTEM)
            .eq(IntegrationRecord::getIntegrationType, INBOUND_TYPE)
            .eq(IntegrationRecord::getProjectId, product.getProductId())
            .eq(IntegrationRecord::getDirection, "inbound")
            .eq(IntegrationRecord::getDeletedFlag, 0)));
        if (inbound == null) {
            return null;
        }
        IntegrationRecord existing = first(integrationRepository.selectList(new LambdaQueryWrapper<IntegrationRecord>()
            .eq(IntegrationRecord::getSourceSystem, SOURCE_SYSTEM)
            .eq(IntegrationRecord::getIntegrationType, OUTBOUND_TYPE)
            .eq(IntegrationRecord::getProjectId, product.getProductId())
            .eq(IntegrationRecord::getNodeKey, node.nodeCode())
            .eq(IntegrationRecord::getDirection, DIRECTION_OUTBOUND)
            .eq(IntegrationRecord::getDeletedFlag, 0)));
        if (existing != null && PROCESSING_SUCCESS.equals(existing.getProcessingStatus())) {
            return toResult(existing, true);
        }

        DingTalkOutboundResult result;
        String processingStatus = PROCESSING_SUCCESS;
        String errorMessage = null;
        try {
            result = outboundClient.startShipMoldProcess(payload(product, node, inbound));
        } catch (Exception ex) {
            processingStatus = "failed";
            errorMessage = ex.getMessage();
            result = new DingTalkOutboundResult(
                "ship-mold-" + product.getProductId() + "-" + node.nodeCode(),
                null,
                "failed",
                "{\"error\":\"" + json(errorMessage) + "\"}"
            );
        }
        IntegrationRecord record = existing == null ? new IntegrationRecord() : existing;
        record.setSourceSystem(SOURCE_SYSTEM);
        record.setIntegrationType(OUTBOUND_TYPE);
        record.setExternalInstanceId(StringUtils.hasText(result.externalInstanceId()) ? result.externalInstanceId()
            : "ship-mold-" + product.getProductId() + "-" + node.nodeCode());
        record.setExternalStatus(StringUtils.hasText(result.externalStatus()) ? result.externalStatus() : "sent");
        record.setProcessCode(properties.getShipMoldProcessCode());
        record.setDirection(DIRECTION_OUTBOUND);
        record.setNodeKey(node.nodeCode());
        record.setExternalUrl(result.externalUrl());
        record.setSourcePayloadJson(result.rawPayloadJson());
        record.setProcessingStatus(processingStatus);
        record.setProjectId(product.getProductId());
        record.setErrorCode(errorMessage == null ? null : "DINGTALK_OUTBOUND_FAILED");
        record.setErrorMessage(errorMessage);
        record.setRetryCount(record.getRetryCount() == null ? 1 : record.getRetryCount() + 1);
        record.setLastTriggeredAt(LocalDateTime.now());
        if (existing == null) {
            fillCreate(record, operator);
            integrationRepository.insert(record);
        } else {
            fillUpdate(record, operator);
            integrationRepository.updateById(record);
        }
        writeLog(product, node, result);
        return toResult(record, false);
    }

    private Map<String, Object> payload(Product product, TimelineNodeDefinition node, IntegrationRecord inbound) {
        RequirementForm form = first(requirementFormRepository.selectList(new LambdaQueryWrapper<RequirementForm>()
            .eq(RequirementForm::getProjectId, product.getProductId())
            .eq(RequirementForm::getDeletedFlag, 0)));
        ProjectMoldTransferExpress express = first(moldTransferExpressRepository.selectList(new LambdaQueryWrapper<ProjectMoldTransferExpress>()
            .eq(ProjectMoldTransferExpress::getProjectId, product.getProductId())
            .eq(ProjectMoldTransferExpress::getTimelineNodeKey, node.nodeCode())
            .eq(ProjectMoldTransferExpress::getDeletedFlag, 0)));
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("processCode", properties.getShipMoldProcessCode());
        payload.put("projectId", product.getProductId());
        payload.put("projectCode", product.getProductCode());
        payload.put("projectName", product.getProductName());
        payload.put("productType", product.getProductType());
        payload.put("model", product.getModel());
        payload.put("nodeKey", node.nodeCode());
        payload.put("nodeName", node.nodeName());
        payload.put("sourceApprovalNo", inbound.getExternalInstanceId());
        payload.put("tipo", form == null ? null : form.getTipo());
        payload.put("moldCodes", form == null ? null : form.getMoldCodes());
        payload.put("moldMatchJson", form == null ? null : form.getMoldMatchJson());
        payload.put("trackingNo", express == null ? null : express.getTrackingNo());
        payload.put("shippedAt", express == null ? null : express.getShippedAt());
        return payload;
    }

    @Transactional
    public DingTalkOutboundTriggerResultVO retry(Long projectId, String operator) {
        Product product = productRepository.selectById(projectId);
        if (product == null || Integer.valueOf(1).equals(product.getDeletedFlag())) {
            throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "项目不存在");
        }
        return triggerIfNeeded(product, new TimelineNodeDefinition(12, "MODEL_VARIANT_MOLD_TRANSFER", "运模到墨西哥"), operator);
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

    private void writeLog(Product product, TimelineNodeDefinition node, DingTalkOutboundResult result) {
        operationLogService.logSuccess(OperationLogCreateCommand.builder()
            .action(OperationActionConstants.DINGTALK_SHIP_MOLD_TRIGGER)
            .businessType("PRODUCT")
            .businessId(String.valueOf(product.getProductId()))
            .businessCode(product.getProductCode())
            .businessName(product.getProductName())
            .detailJson("{\"action\":\"ship_mold_to_dingtalk\",\"nodeKey\":\"" + node.nodeCode()
                + "\",\"externalStatus\":\"" + (result.externalStatus() == null ? "" : result.externalStatus()) + "\"}")
            .build());
    }

    private String json(String value) {
        if (value == null) {
            return "";
        }
        return value.replace("\\", "\\\\").replace("\"", "\\\"");
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

    private <T> T first(List<T> values) {
        return values == null || values.isEmpty() ? null : values.get(0);
    }
}
