package com.yuewei.plm.module.integration.dingtalk.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.util.ProductBusinessCodeGenerator;
import com.yuewei.plm.common.util.ProductCodeGenerator;
import com.yuewei.plm.module.integration.dingtalk.dto.DingTalkProductLineReceiveDTO;
import com.yuewei.plm.module.integration.dingtalk.entity.IntegrationRecord;
import com.yuewei.plm.module.integration.dingtalk.repository.IntegrationRecordRepository;
import com.yuewei.plm.module.integration.dingtalk.vo.DingTalkProductLineResultVO;
import com.yuewei.plm.module.operationlog.constant.OperationActionConstants;
import com.yuewei.plm.module.operationlog.service.OperationLogCreateCommand;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.workflow.entity.WorkflowTemplate;
import com.yuewei.plm.module.workflow.service.WorkflowTemplateService;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.BaseEntity;
import com.yuewei.plm.repository.entity.Product;
import java.time.LocalDateTime;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

@Service
@RequiredArgsConstructor
public class DingTalkProductLineService {
    private static final String SOURCE_SYSTEM = "dingtalk";
    private static final String INTEGRATION_TYPE = "product_line";
    private static final String DIRECTION_INBOUND = "inbound";
    private final ProductBusinessCodeGenerator businessCodeGenerator = new ProductBusinessCodeGenerator();

    private final ProductRepository productRepository;
    private final IntegrationRecordRepository integrationRepository;
    private final ProductCodeGenerator productCodeGenerator;
    private final DingTalkAttachmentArchiveService attachmentArchiveService;
    private final OperationLogService operationLogService;
    private final WorkflowTemplateService workflowTemplateService;

    @Transactional
    public DingTalkProductLineResultVO receive(DingTalkProductLineReceiveDTO dto) {
        String externalInstanceId = externalInstanceId(dto);
        IntegrationRecord existing = first(integrationRepository.selectList(new LambdaQueryWrapper<IntegrationRecord>()
            .eq(IntegrationRecord::getSourceSystem, SOURCE_SYSTEM)
            .eq(IntegrationRecord::getIntegrationType, INTEGRATION_TYPE)
            .eq(IntegrationRecord::getExternalInstanceId, externalInstanceId)
            .eq(IntegrationRecord::getDeletedFlag, 0)));
        if (existing != null) {
            return result(existing, true, "already_recorded");
        }

        if (!"approved".equals(dto.getApprovalStatus())) {
            IntegrationRecord ignored = saveRecord(dto, null, "ignored");
            return result(ignored, false, "not_provided");
        }

        Product product = new Product();
        String productSpecificCode = resolveProductSpecificCode(dto.getProductCodePrefix());
        product.setProductType("product_line");
        product.setProductName(dto.getProductName().trim());
        product.setProductCodePrefix(StringUtils.hasText(productSpecificCode) ? productSpecificCode : dto.getProductCodePrefix());
        product.setProductSpecificCode(productSpecificCode);
        product.setMoldCodePrefix(dto.getMoldCodePrefix());
        product.setProductCode(generateUniqueProductCode(dto, productSpecificCode));
        product.setColor(dto.getProductionColors());
        product.setMaterial(dto.getMoldMaterials());
        product.setVersionNo("A");
        product.setStatus("developing");
        product.setCurrentStepNo(1);
        product.setTimelineCurrentConfirmed(false);
        product.setLockStatus("unlocked");
        product.setExpectedDeliveryDate(dto.getExpectedDeliveryDate());
        product.setSourceSystem(SOURCE_SYSTEM);
        product.setSourceInstanceId(externalInstanceId);
        product.setSourceFormUrl(dto.getFormUrl());
        product.setSourceApprovedAt(dto.getSourceApprovedAt());
        product.setRemark(dto.getRemark());
        bindWorkflowTemplate(product);
        String operator = operator(dto);
        fill(product, operator, LocalDateTime.now());
        productRepository.insert(product);

        String attachmentStatus = attachmentArchiveService.archiveMetadata(dto.getAttachments(), product, null, "other", operator);
        IntegrationRecord record = saveRecord(dto, product.getProductId(), "success");
        writeLog(product);
        return result(record, false, attachmentStatus);
    }

    private String generateUniqueProductCode(DingTalkProductLineReceiveDTO dto, String productSpecificCode) {
        String productLineCode = resolveProductLineCode(dto.getProductCodePrefix(), productSpecificCode);
        if (StringUtils.hasText(productLineCode)) {
            Long count = productRepository.selectCount(new LambdaQueryWrapper<Product>().eq(Product::getProductCode, productLineCode));
            if (count == null || count == 0) {
                return productLineCode;
            }
            throw validation("产品编码已存在: " + productLineCode);
        }
        String seed = StringUtils.hasText(dto.getProductCodePrefix()) ? dto.getProductCodePrefix() : dto.getProductName();
        for (int attempt = 0; attempt < 10000; attempt++) {
            String candidate = productCodeGenerator.generate(seed);
            Long count = productRepository.selectCount(new LambdaQueryWrapper<Product>().eq(Product::getProductCode, candidate));
            if (count == null || count == 0) return candidate;
        }
        throw validation("无法生成唯一产品编码");
    }

    private String resolveProductLineCode(String value, String productSpecificCode) {
        String normalized = normalizeCompactCode(value);
        String product = StringUtils.hasText(productSpecificCode) ? productSpecificCode : resolveProductSpecificCode(value);
        String explicitCode = normalizeProductLineCodeCandidate(normalized, product);
        if (StringUtils.hasText(explicitCode)) {
            return explicitCode;
        }
        if (!StringUtils.hasText(product)) {
            return null;
        }
        return businessCodeGenerator.generateProductLineCode(
            product,
            ProductBusinessCodeGenerator.DEFAULT_FINAL_OPERATION_CODE
        );
    }

    private String resolveProductSpecificCode(String value) {
        String normalized = normalizeCompactCode(value);
        if (!StringUtils.hasText(normalized)) {
            return null;
        }
        String body = normalized.startsWith(ProductBusinessCodeGenerator.PRODUCT_STATE_PREFIX)
            ? normalized.substring(ProductBusinessCodeGenerator.PRODUCT_STATE_PREFIX.length())
            : normalized;
        if (body.length() > 4 && body.substring(body.length() - 4).matches("\\d{4}")) {
            return body.substring(0, body.length() - 4);
        }
        return body;
    }

    private String normalizeProductLineCodeCandidate(String value, String expectedProductSpecificCode) {
        if (!StringUtils.hasText(value)) {
            return null;
        }
        String body = value.startsWith(ProductBusinessCodeGenerator.PRODUCT_STATE_PREFIX)
            ? value.substring(ProductBusinessCodeGenerator.PRODUCT_STATE_PREFIX.length())
            : value;
        if (body.length() <= 4 || !body.substring(body.length() - 4).matches("\\d{4}")) {
            return null;
        }
        String product = body.substring(0, body.length() - 4);
        if (StringUtils.hasText(expectedProductSpecificCode) && !expectedProductSpecificCode.equals(product)) {
            return null;
        }
        return businessCodeGenerator.generateProductLineCode(product, body.substring(body.length() - 4));
    }

    private String normalizeCompactCode(String value) {
        return StringUtils.hasText(value) ? value.trim().toUpperCase().replace("-", "") : null;
    }

    private IntegrationRecord saveRecord(DingTalkProductLineReceiveDTO dto, Long projectId, String processingStatus) {
        IntegrationRecord record = new IntegrationRecord();
        record.setSourceSystem(SOURCE_SYSTEM);
        record.setIntegrationType(INTEGRATION_TYPE);
        record.setExternalInstanceId(externalInstanceId(dto));
        record.setExternalStatus(dto.getApprovalStatus());
        record.setProcessCode(dto.getProcessCode());
        record.setDirection(DIRECTION_INBOUND);
        record.setExternalUrl(dto.getFormUrl());
        record.setSourcePayloadJson(dto.getSourcePayloadJson());
        record.setProcessingStatus(processingStatus);
        record.setProjectId(projectId);
        record.setRetryCount(0);
        fill(record, operator(dto), LocalDateTime.now());
        integrationRepository.insert(record);
        return record;
    }

    private DingTalkProductLineResultVO result(IntegrationRecord record, boolean hit, String attachmentStatus) {
        Product product = record.getProjectId() == null ? null : productRepository.selectById(record.getProjectId());
        return DingTalkProductLineResultVO.builder()
            .integrationRecordId(record.getIntegrationRecordId())
            .projectId(record.getProjectId())
            .productCode(product == null ? null : product.getProductCode())
            .productName(product == null ? null : product.getProductName())
            .productType(product == null ? "product_line" : product.getProductType())
            .dingTalkApprovalNo(record.getExternalInstanceId())
            .status(record.getProcessingStatus())
            .idempotentHit(hit)
            .attachmentArchiveStatus(attachmentStatus)
            .build();
    }

    private String externalInstanceId(DingTalkProductLineReceiveDTO dto) {
        if (StringUtils.hasText(dto.getApprovalInstanceId())) return dto.getApprovalInstanceId();
        if (StringUtils.hasText(dto.getApprovalNo())) return dto.getApprovalNo();
        throw validation("钉钉审批实例 ID 不能为空");
    }

    private String operator(DingTalkProductLineReceiveDTO dto) {
        return StringUtils.hasText(dto.getApplicantUserName()) ? dto.getApplicantUserName() : "dingtalk";
    }

    private void writeLog(Product product) {
        operationLogService.logSuccess(OperationLogCreateCommand.builder()
            .action(OperationActionConstants.DINGTALK_PRODUCT_LINE_CREATE)
            .businessType("PRODUCT")
            .businessId(String.valueOf(product.getProductId()))
            .businessCode(product.getProductCode())
            .businessName(product.getProductName())
            .detailJson("{\"action\":\"dingtalk_product_line_create\"}")
            .build());
    }

    private void bindWorkflowTemplate(Product product) {
        WorkflowTemplate template = workflowTemplateService.findActiveTemplate(product.getProductType());
        if (template == null) {
            return;
        }
        product.setWorkflowTemplateId(template.getWorkflowTemplateId());
        product.setWorkflowTemplateVersionNo(template.getVersionNo());
    }

    private void fill(BaseEntity entity, String operator, LocalDateTime now) {
        entity.setCreatedAt(now);
        entity.setCreatedBy(operator);
        entity.setUpdatedAt(now);
        entity.setUpdatedBy(operator);
        entity.setDeletedFlag(0);
    }

    private <T> T first(List<T> values) {
        return values == null || values.isEmpty() ? null : values.get(0);
    }

    private BusinessException validation(String message) {
        return new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, message);
    }
}
