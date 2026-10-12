package com.yuewei.plm.module.process.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.util.ProductBusinessCodeGenerator;
import com.yuewei.plm.module.bom.entity.ProductBom;
import com.yuewei.plm.module.bom.entity.ProductBomRoute;
import com.yuewei.plm.module.bom.entity.ProductBomRouteColor;
import com.yuewei.plm.module.bom.repository.ProductBomRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteColorRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteRepository;
import com.yuewei.plm.module.process.entity.ProcessEntity;
import com.yuewei.plm.module.process.repository.ProcessRepository;
import com.yuewei.plm.repository.entity.Product;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

@Service
@RequiredArgsConstructor
public class ProcessRouteInheritanceService {

    private static final String TYPE_ROUTING = "routing";
    private static final String TYPE_OPERATION = "operation";
    private static final String STATUS_CONFIRMED = "confirmed";
    private static final int PROCESS_CODE_MAX_LENGTH = 20;

    private final ProductBomRepository bomRepository;
    private final ProductBomRouteRepository bomRouteRepository;
    private final ProductBomRouteColorRepository bomRouteColorRepository;
    private final ProcessRepository processRepository;
    private final ProductBusinessCodeGenerator businessCodeGenerator = new ProductBusinessCodeGenerator();
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Transactional
    public Map<Long, Long> inheritLatestReleasedFormalBomRoutesByColors(Long sourceProductId,
                                                                         Product targetProduct,
                                                                         List<String> selectedColors,
                                                                         String operator) {
        Set<String> selected = selectedColors == null ? Set.of() : selectedColors.stream()
            .filter(StringUtils::hasText)
            .map(String::trim)
            .collect(Collectors.toSet());
        if (selected.isEmpty()) {
            return Map.of();
        }
        ProductBom sourceBom = latestReleasedFormalBom(sourceProductId);
        List<ProductBomRoute> sourceRoutes = bomRouteRepository.selectList(new LambdaQueryWrapper<ProductBomRoute>()
            .eq(ProductBomRoute::getProductBomId, sourceBom.getProductBomId())
            .eq(ProductBomRoute::getStatus, "active")
            .eq(ProductBomRoute::getDeletedFlag, 0)
            .orderByAsc(ProductBomRoute::getProductBomRouteId));
        if (sourceRoutes == null || sourceRoutes.isEmpty()) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "父产品已发布正式 BOM 没有关联工艺路线，不能创建新型号线");
        }

        Map<Long, Long> processIdMapping = new LinkedHashMap<>();
        LocalDateTime now = LocalDateTime.now();
        String inheritedBy = StringUtils.hasText(operator) ? operator : "system";
        for (ProductBomRoute sourceRoute : sourceRoutes) {
            if (sourceRoute.getProcessId() == null || !hasSelectedColor(sourceRoute.getProductBomRouteId(), selected)) {
                continue;
            }
            processIdMapping.computeIfAbsent(sourceRoute.getProcessId(),
                sourceProcessId -> copyProcessRouteTree(sourceProcessId, targetProduct, now, inheritedBy));
        }
        if (processIdMapping.isEmpty()) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "父产品已发布正式 BOM 没有命中敲定颜色的工艺路线，不能创建新型号线");
        }
        return processIdMapping;
    }

    private ProductBom latestReleasedFormalBom(Long sourceProductId) {
        List<ProductBom> sources = bomRepository.selectList(new LambdaQueryWrapper<ProductBom>()
            .eq(ProductBom::getProductId, sourceProductId)
            .eq(ProductBom::getBomScope, "formal")
            .eq(ProductBom::getStatus, "released")
            .eq(ProductBom::getDeletedFlag, 0)
            .orderByDesc(ProductBom::getUpdatedAt));
        if (sources == null || sources.isEmpty()) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "父产品没有已发布正式 BOM，不能创建新型号线");
        }
        return sources.get(0);
    }

    private boolean hasSelectedColor(Long sourceBomRouteId, Set<String> selectedColors) {
        List<ProductBomRouteColor> colors = bomRouteColorRepository.selectList(new LambdaQueryWrapper<ProductBomRouteColor>()
            .eq(ProductBomRouteColor::getProductBomRouteId, sourceBomRouteId)
            .eq(ProductBomRouteColor::getStatus, "active")
            .eq(ProductBomRouteColor::getDeletedFlag, 0));
        return colors != null && colors.stream()
            .map(ProductBomRouteColor::getColorName)
            .filter(StringUtils::hasText)
            .map(String::trim)
            .anyMatch(selectedColors::contains);
    }

    private Long copyProcessRouteTree(Long sourceProcessId, Product targetProduct, LocalDateTime now, String operator) {
        ProcessEntity sourceRoute = processRepository.selectById(sourceProcessId);
        if (sourceRoute == null || Integer.valueOf(1).equals(sourceRoute.getDeletedFlag())
            || !TYPE_ROUTING.equals(sourceRoute.getProcessType())) {
            throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "父产品正式 BOM 关联的工艺路线不存在");
        }
        validateProductCodeContext(targetProduct);

        ProcessEntity targetRoute = copyRoute(sourceRoute, targetProduct, now, operator);
        processRepository.insert(targetRoute);

        List<ProcessEntity> sourceOperations = processRepository.selectList(new LambdaQueryWrapper<ProcessEntity>()
            .eq(ProcessEntity::getParentProcessId, sourceProcessId)
            .eq(ProcessEntity::getProcessType, TYPE_OPERATION)
            .eq(ProcessEntity::getDeletedFlag, 0)
            .orderByAsc(ProcessEntity::getSequenceNo));
        if (sourceOperations != null) {
            for (ProcessEntity sourceOperation : sourceOperations) {
                processRepository.insert(copyOperation(sourceOperation, targetRoute, targetProduct, now, operator));
            }
        }
        return targetRoute.getProcessId();
    }

    private ProcessEntity copyRoute(ProcessEntity source, Product targetProduct, LocalDateTime now, String operator) {
        ProcessEntity target = new ProcessEntity();
        target.setProductId(targetProduct.getProductId());
        target.setProcessCode(uniqueProcessCode(buildRouteCode(targetProduct, source)));
        target.setProcessName(ProcessRouteNamingRules.routeName(source.getProcessName(), targetProduct));
        target.setProcessType(TYPE_ROUTING);
        target.setVersionNo(source.getVersionNo());
        target.setProcessParamJson(source.getProcessParamJson());
        target.setStandardTimeMins(source.getStandardTimeMins());
        target.setQualityRequirement(source.getQualityRequirement());
        target.setStatus(STATUS_CONFIRMED);
        target.setRemark(source.getRemark());
        fillCreate(target, now, operator);
        return target;
    }

    private ProcessEntity copyOperation(ProcessEntity source, ProcessEntity targetRoute, Product targetProduct,
                                        LocalDateTime now, String operator) {
        ProcessEntity target = new ProcessEntity();
        target.setParentProcessId(targetRoute.getProcessId());
        target.setOperationMasterProcessId(source.getOperationMasterProcessId());
        target.setProductId(targetProduct.getProductId());
        target.setProcessCode(uniqueProcessCode(buildOperationCode(targetRoute, source)));
        target.setProcessName(source.getProcessName());
        target.setProcessType(TYPE_OPERATION);
        String operationCraftCode = normalizeOperationCraftCode(source.getOperationCraftCode());
        target.setOperationCraftCode(operationCraftCode);
        target.setMaterialStatusCode(source.getMaterialStatusCode());
        target.setFinishedProductFlag(source.getFinishedProductFlag());
        CodeGenerationContext context = resolveCodeGenerationContext(targetProduct, operationCraftCode);
        String businessOperationCode = resolveBusinessOperationCode(source, context);
        target.setBusinessOperationCode(businessOperationCode);
        target.setBusinessOperationCodeManualFlag(false);
        target.setProductSpecificCode(context.productSpecificCode());
        target.setPhoneModelCode(context.phoneModelCode());
        target.setColorCode(context.colorCode());
        target.setGeneratedFinishedProductCode(resolveGeneratedFinishedProductCode(operationCraftCode, businessOperationCode));
        target.setCodeGenerationContext(context.contextName());
        target.setVersionNo(targetRoute.getVersionNo());
        target.setSequenceNo(source.getSequenceNo());
        target.setProcessParamJson(rebuildOperationParams(source, businessOperationCode, target.getGeneratedFinishedProductCode(), context));
        target.setStandardTimeMins(source.getStandardTimeMins());
        target.setQualityRequirement(source.getQualityRequirement());
        target.setStatus(STATUS_CONFIRMED);
        target.setRemark(source.getRemark());
        fillCreate(target, now, operator);
        return target;
    }

    @SuppressWarnings("unchecked")
    private String rebuildOperationParams(ProcessEntity source, String businessOperationCode,
                                          String generatedFinishedProductCode, CodeGenerationContext context) {
        Map<String, Object> params = new LinkedHashMap<>();
        if (StringUtils.hasText(source.getProcessParamJson())) {
            try {
                params.putAll(objectMapper.readValue(source.getProcessParamJson(), Map.class));
            } catch (Exception ignored) {
                params.put("sourceProcessParamJson", source.getProcessParamJson());
            }
        }
        params.put("businessOperationCode", businessOperationCode);
        params.put("businessOperationCodeManualFlag", false);
        params.put("operationCraftCode", context.operationCraftCode());
        params.put("productSpecificCode", context.productSpecificCode());
        params.put("phoneModelCode", context.phoneModelCode());
        params.put("colorCode", context.colorCode());
        params.put("generatedFinishedProductCode", generatedFinishedProductCode);
        params.put("codeGenerationContext", context.contextName());
        try {
            return objectMapper.writeValueAsString(params);
        } catch (Exception ex) {
            return source.getProcessParamJson();
        }
    }

    private CodeGenerationContext resolveCodeGenerationContext(Product product, String operationCraftCode) {
        String contextName = resolveCodeGenerationContextName(product);
        String productSpecificCode = normalizeCompactCode(product.getProductSpecificCode());
        String phoneModelCode = product.getPhoneModelCode();
        String colorCode = product.getColorCode();
        if ("product_line_route".equals(contextName)) {
            phoneModelCode = null;
            colorCode = null;
        } else if ("model_variant_route".equals(contextName)) {
            phoneModelCode = normalizeCodeOrNull(phoneModelCode);
            colorCode = null;
            validatePhoneModelCode(phoneModelCode);
        } else {
            phoneModelCode = normalizeCodeOrNull(phoneModelCode);
            colorCode = normalizeCodeOrNull(colorCode);
            validateConcreteCodeContext(phoneModelCode, colorCode);
        }
        return new CodeGenerationContext(
            productSpecificCode,
            normalizeOperationCraftCode(operationCraftCode),
            phoneModelCode,
            colorCode,
            contextName
        );
    }

    private void validateProductCodeContext(Product product) {
        String contextName = resolveCodeGenerationContextName(product);
        if ("product_line_route".equals(contextName)) {
            return;
        }
        String phoneModelCode = normalizeCodeOrNull(product.getPhoneModelCode());
        if ("model_variant_route".equals(contextName)) {
            validatePhoneModelCode(phoneModelCode);
            return;
        }
        validateConcreteCodeContext(
            phoneModelCode,
            normalizeCodeOrNull(product.getColorCode())
        );
    }

    private void validatePhoneModelCode(String phoneModelCode) {
        if (!StringUtils.hasText(phoneModelCode) || !phoneModelCode.matches("[A-Z0-9]{4}")) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR,
                "具体型号或 SKU 必须提供 4 位手机型号编码");
        }
    }

    private void validateConcreteCodeContext(String phoneModelCode, String colorCode) {
        if (!StringUtils.hasText(phoneModelCode) || !phoneModelCode.matches("[A-Z0-9]{4}")) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR,
                "具体型号或 SKU 必须提供 4 位手机型号编码");
        }
        if (!StringUtils.hasText(colorCode) || !colorCode.matches("[A-Z0-9]{2}")) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR,
                "具体颜色或 SKU 必须提供 2 位颜色编码");
        }
    }

    private String resolveCodeGenerationContextName(Product product) {
        String productType = normalizeCode(product.getProductType());
        return switch (productType == null ? "" : productType) {
            case "SKU" -> "sku_route";
            case "MODEL_VARIANT" -> "model_variant_route";
            default -> "product_line_route";
        };
    }

    private String resolveBusinessOperationCode(ProcessEntity source, CodeGenerationContext context) {
        String baseCode = StringUtils.hasText(source.getBusinessOperationCode())
            ? normalizeCode(source.getBusinessOperationCode())
            : buildProductLineBusinessOperationCode(context.productSpecificCode(), context.operationCraftCode());
        if (!StringUtils.hasText(baseCode)) {
            return null;
        }
        if ("product_line_route".equals(context.contextName())) {
            return baseCode;
        }
        String modelCode = appendSuffixIfMissing(baseCode, context.phoneModelCode());
        if ("model_variant_route".equals(context.contextName())) {
            return modelCode;
        }
        return appendSuffixIfMissing(modelCode, context.colorCode());
    }

    private String buildProductLineBusinessOperationCode(String productSpecificCode, String operationCraftCode) {
        String product = normalizeCompactCode(productSpecificCode);
        String operation = normalizeOperationCraftCode(operationCraftCode);
        if (!StringUtils.hasText(product) || !StringUtils.hasText(operation)) {
            return null;
        }
        return ProductBusinessCodeGenerator.PRODUCT_STATE_PREFIX + product + operation;
    }

    private String appendSuffixIfMissing(String value, String suffix) {
        String normalizedValue = normalizeCode(value);
        String normalizedSuffix = normalizeCompactCode(suffix);
        if (!StringUtils.hasText(normalizedValue) || !StringUtils.hasText(normalizedSuffix)) {
            return normalizedValue;
        }
        return normalizedValue.endsWith(normalizedSuffix) ? normalizedValue : normalizedValue + normalizedSuffix;
    }

    private String resolveGeneratedFinishedProductCode(String operationCraftCode, String businessOperationCode) {
        if (!StringUtils.hasText(operationCraftCode) || !StringUtils.hasText(businessOperationCode)) {
            return null;
        }
        return ProductBusinessCodeGenerator.DEFAULT_FINAL_OPERATION_CODE.equals(normalizeCode(operationCraftCode))
            ? businessOperationCode
            : null;
    }

    private String normalizeCompactCode(String value) {
        String normalized = normalizeCode(value);
        return StringUtils.hasText(normalized) ? normalized.replace("-", "") : null;
    }

    private String normalizeCodeOrNull(String value) {
        return normalizeCompactCode(value);
    }

    private String normalizeOperationCraftCode(String value) {
        String normalized = normalizeCode(value);
        if (!StringUtils.hasText(normalized)) {
            return null;
        }
        return switch (normalized) {
            case "10" -> "1010";
            case "20", "30", "51", "52" -> "1020";
            case "40" -> ProductBusinessCodeGenerator.DEFAULT_FINAL_OPERATION_CODE;
            default -> normalized;
        };
    }

    private String normalizeCode(String value) {
        return StringUtils.hasText(value) ? value.trim().toUpperCase() : null;
    }

    private String buildRouteCode(Product targetProduct, ProcessEntity sourceRoute) {
        return limit(ProcessRouteNamingRules.inheritedRouteCode(targetProduct, sourceRoute));
    }

    private String buildOperationCode(ProcessEntity targetRoute, ProcessEntity sourceOperation) {
        String sequence = sourceOperation.getSequenceNo() == null
            ? String.valueOf(sourceOperation.getProcessId())
            : String.format("%03d", sourceOperation.getSequenceNo());
        return limit(targetRoute.getProcessCode() + "-OP" + sequence);
    }

    private String uniqueProcessCode(String baseCode) {
        String normalized = limit(baseCode);
        String candidate = normalized;
        int index = 2;
        while (existsProcessCode(candidate)) {
            String suffix = "-" + index++;
            candidate = limit(normalized, PROCESS_CODE_MAX_LENGTH - suffix.length()) + suffix;
        }
        return candidate;
    }

    private boolean existsProcessCode(String processCode) {
        Long count = processRepository.selectCount(new LambdaQueryWrapper<ProcessEntity>()
            .eq(ProcessEntity::getProcessCode, processCode)
            .eq(ProcessEntity::getDeletedFlag, 0));
        return count != null && count > 0;
    }

    private String limit(String value) {
        return limit(value, PROCESS_CODE_MAX_LENGTH);
    }

    private String limit(String value, int maxLength) {
        if (value.length() <= maxLength) {
            return value;
        }
        return value.substring(0, maxLength);
    }

    private void fillCreate(ProcessEntity entity, LocalDateTime now, String operator) {
        entity.setCreatedAt(now);
        entity.setCreatedBy(operator);
        entity.setUpdatedAt(now);
        entity.setUpdatedBy(operator);
        entity.setDeletedFlag(0);
    }

    private record CodeGenerationContext(String productSpecificCode, String operationCraftCode, String phoneModelCode,
                                         String colorCode, String contextName) {
    }
}
