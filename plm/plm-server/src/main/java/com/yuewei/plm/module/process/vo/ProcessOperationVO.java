package com.yuewei.plm.module.process.vo;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.module.process.entity.ProcessEntity;
import java.math.BigDecimal;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ProcessOperationVO {

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    private Long processId;
    private Long parentProcessId;
    private Long operationMasterProcessId;
    private String operationSource;
    private String processCode;
    private String operationCode;
    private String operationCraftCode;
    private String materialStatusCode;
    private Boolean finishedProductFlag;
    private String businessOperationCode;
    private Boolean businessOperationCodeManualFlag;
    private String productSpecificCode;
    private String phoneModelCode;
    private String colorCode;
    private String generatedFinishedProductCode;
    private String codeGenerationContext;
    private Integer sequenceNo;
    private String processName;
    private String processParamJson;
    private BigDecimal standardTimeMins;
    private String qualityRequirement;
    private String status;
    private String remark;

    public static ProcessOperationVO from(ProcessEntity entity) {
        return ProcessOperationVO.builder()
            .processId(entity.getProcessId())
            .parentProcessId(entity.getParentProcessId())
            .operationMasterProcessId(entity.getOperationMasterProcessId())
            .operationSource(resolveOperationSource(entity))
            .processCode(entity.getProcessCode())
            .operationCode(extractOperationCode(entity.getProcessParamJson()))
            .operationCraftCode(resolveText(entity.getOperationCraftCode(), entity.getProcessParamJson(), "operationCraftCode"))
            .materialStatusCode(resolveText(entity.getMaterialStatusCode(), entity.getProcessParamJson(), "materialStatusCode"))
            .finishedProductFlag(resolveBoolean(entity.getFinishedProductFlag(), entity.getProcessParamJson(), "finishedProductFlag"))
            .businessOperationCode(resolveText(entity.getBusinessOperationCode(), entity.getProcessParamJson(), "businessOperationCode"))
            .businessOperationCodeManualFlag(resolveBoolean(entity.getBusinessOperationCodeManualFlag(), entity.getProcessParamJson(), "businessOperationCodeManualFlag"))
            .productSpecificCode(resolveText(entity.getProductSpecificCode(), entity.getProcessParamJson(), "productSpecificCode"))
            .phoneModelCode(resolveText(entity.getPhoneModelCode(), entity.getProcessParamJson(), "phoneModelCode"))
            .colorCode(resolveText(entity.getColorCode(), entity.getProcessParamJson(), "colorCode"))
            .generatedFinishedProductCode(resolveText(entity.getGeneratedFinishedProductCode(), entity.getProcessParamJson(), "generatedFinishedProductCode"))
            .codeGenerationContext(resolveText(entity.getCodeGenerationContext(), entity.getProcessParamJson(), "codeGenerationContext"))
            .sequenceNo(entity.getSequenceNo())
            .processName(entity.getProcessName())
            .processParamJson(entity.getProcessParamJson())
            .standardTimeMins(entity.getStandardTimeMins())
            .qualityRequirement(entity.getQualityRequirement())
            .status(entity.getStatus())
            .remark(entity.getRemark())
            .build();
    }

    private static String extractOperationCode(String processParamJson) {
        return resolveText(null, processParamJson, "operationCode");
    }

    private static String resolveText(String directValue, String processParamJson, String fieldName) {
        if (directValue != null && !directValue.isBlank()) {
            return directValue;
        }
        if (processParamJson == null || processParamJson.isBlank()) {
            return null;
        }
        try {
            JsonNode node = OBJECT_MAPPER.readTree(processParamJson);
            JsonNode value = node.get(fieldName);
            return value == null || value.isNull() ? null : value.asText();
        } catch (Exception ignored) {
            return null;
        }
    }

    private static Boolean resolveBoolean(Boolean directValue, String processParamJson, String fieldName) {
        if (directValue != null) {
            return directValue;
        }
        if (processParamJson == null || processParamJson.isBlank()) {
            return Boolean.FALSE;
        }
        try {
            JsonNode node = OBJECT_MAPPER.readTree(processParamJson);
            JsonNode value = node.get(fieldName);
            return value != null && !value.isNull() && value.asBoolean(false);
        } catch (Exception ignored) {
            return Boolean.FALSE;
        }
    }

    private static boolean historicalSnapshot(ProcessEntity entity) {
        return entity.getRemark() != null && entity.getRemark().contains("历史存档导入");
    }

    private static String resolveOperationSource(ProcessEntity entity) {
        String persisted = resolveText(null, entity.getProcessParamJson(), "operationSource");
        if (persisted != null && !persisted.isBlank()) {
            return persisted;
        }
        if (historicalSnapshot(entity)) {
            return "imported_snapshot";
        }
        return entity.getOperationMasterProcessId() != null ? "master" : "manual_snapshot";
    }
}
