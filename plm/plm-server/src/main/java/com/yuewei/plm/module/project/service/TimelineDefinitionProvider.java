package com.yuewei.plm.module.project.service;

import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.module.project.constant.TimelineNodeConstants;
import com.yuewei.plm.module.project.constant.TimelineNodeConstants.TimelineNodeDefinition;
import com.yuewei.plm.module.workflow.service.WorkflowDefinitionProvider;
import com.yuewei.plm.repository.entity.Product;
import java.util.List;
import java.util.Objects;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

@Component
public class TimelineDefinitionProvider {

    @Autowired(required = false)
    private WorkflowDefinitionProvider workflowDefinitionProvider;

    public List<TimelineNodeDefinition> getDefinitions(String productType) {
        if (workflowDefinitionProvider != null) {
            List<TimelineNodeDefinition> definitions = workflowDefinitionProvider.getDefinitions(workflowFlowType(productType));
            if (!definitions.isEmpty()) {
                return normalizeDefinitions(productType, definitions);
            }
        }
        return fallbackDefinitions(productType);
    }

    public List<TimelineNodeDefinition> getDefinitions(Product product) {
        if (product != null && workflowDefinitionProvider != null) {
            List<TimelineNodeDefinition> definitions = TimelineNodeConstants.PRODUCT_TYPE_SKU.equals(product.getProductType())
                ? workflowDefinitionProvider.getDefinitions(TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT)
                : workflowDefinitionProvider.getDefinitions(product);
            if (!definitions.isEmpty()) {
                return normalizeDefinitions(product.getProductType(), definitions);
            }
        }
        return getDefinitions(product == null ? null : product.getProductType());
    }

    private List<TimelineNodeDefinition> normalizeDefinitions(String productType, List<TimelineNodeDefinition> definitions) {
        if (!isModelVariantTimeline(productType)) {
            return definitions;
        }
        int moldTransferIndex = -1;
        for (int i = 0; i < definitions.size(); i++) {
            if ("MODEL_VARIANT_MOLD_TRANSFER".equals(definitions.get(i).nodeCode())) {
                moldTransferIndex = i;
                break;
            }
        }
        if (moldTransferIndex < 0) {
            return definitions;
        }
        return definitions.subList(0, moldTransferIndex + 1);
    }

    private List<TimelineNodeDefinition> fallbackDefinitions(String productType) {
        if (TimelineNodeConstants.PRODUCT_TYPE_PRODUCT_LINE.equals(productType)) {
            return TimelineNodeConstants.PRODUCT_LINE_NODES;
        }
        if (isModelVariantTimeline(productType)) {
            return TimelineNodeConstants.MODEL_VARIANT_NODES;
        }
        throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "不支持的产品类型");
    }

    private boolean isModelVariantTimeline(String productType) {
        return TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT.equals(productType)
            || TimelineNodeConstants.PRODUCT_TYPE_SKU.equals(productType);
    }

    private String workflowFlowType(String productType) {
        return TimelineNodeConstants.PRODUCT_TYPE_SKU.equals(productType)
            ? TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT
            : productType;
    }

    public String getCurrentNodeName(String productType, Integer currentStepNo) {
        List<TimelineNodeDefinition> definitions = getDefinitions(productType);
        int normalizedStepNo = normalizeStepNo(currentStepNo, definitions.size());
        return definitions.get(normalizedStepNo - 1).nodeName();
    }

    public String getCurrentNodeName(Product product, Integer currentStepNo) {
        List<TimelineNodeDefinition> definitions = getDefinitions(product);
        int normalizedStepNo = normalizeStepNo(currentStepNo, definitions.size());
        return definitions.get(normalizedStepNo - 1).nodeName();
    }

    public TimelineNodeDefinition getDefinitionByCode(String productType, String nodeCode) {
        return getDefinitions(productType).stream()
            .filter(definition -> definition.nodeCode().equals(nodeCode))
            .findFirst()
            .orElseThrow(() -> new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "时间轴步骤不存在"));
    }

    public TimelineNodeDefinition getDefinitionByCode(Product product, String nodeCode) {
        return getDefinitions(product).stream()
            .filter(definition -> definition.nodeCode().equals(nodeCode))
            .findFirst()
            .orElseThrow(() -> new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "时间轴步骤不存在"));
    }

    public TimelineNodeDefinition getDefinitionByStepNo(String productType, Integer currentStepNo) {
        List<TimelineNodeDefinition> definitions = getDefinitions(productType);
        int normalizedStepNo = normalizeStepNo(currentStepNo, definitions.size());
        return definitions.get(normalizedStepNo - 1);
    }

    public TimelineNodeDefinition getDefinitionByStepNo(Product product, Integer currentStepNo) {
        List<TimelineNodeDefinition> definitions = getDefinitions(product);
        int normalizedStepNo = normalizeStepNo(currentStepNo, definitions.size());
        return definitions.get(normalizedStepNo - 1);
    }

    public boolean isLastStepOfStage(String productType, TimelineNodeDefinition definition) {
        List<TimelineNodeDefinition> definitions = getDefinitions(productType);
        int index = definitions.indexOf(definition);
        if (index < 0 || index == definitions.size() - 1) {
            return true;
        }
        TimelineNodeDefinition next = definitions.get(index + 1);
        return !Objects.equals(definition.stageCode(), next.stageCode());
    }

    public List<String> getStageStepCodes(String productType, String stageCode) {
        return getDefinitions(productType).stream()
            .filter(definition -> definition.stageCode().equals(stageCode))
            .map(TimelineNodeDefinition::nodeCode)
            .toList();
    }

    public List<TimelineNodeDefinition> getRequiredDefinitionsForStage(String productType, String stageCode) {
        return getDefinitions(productType).stream()
            .filter(definition -> definition.stageCode().equals(stageCode))
            .filter(definition -> definition.requiredFileCategory() != null && !definition.requiredFileCategory().isBlank())
            .toList();
    }

    public List<TimelineNodeDefinition> getRequiredDefinitionsForStage(Product product, String stageCode) {
        return getDefinitions(product).stream()
            .filter(definition -> definition.stageCode().equals(stageCode))
            .filter(definition -> definition.requiredFileCategory() != null && !definition.requiredFileCategory().isBlank())
            .toList();
    }

    private int normalizeStepNo(Integer currentStepNo, int maxStepNo) {
        if (currentStepNo == null || currentStepNo < 1) {
            return 1;
        }
        return Math.min(currentStepNo, maxStepNo);
    }
}
