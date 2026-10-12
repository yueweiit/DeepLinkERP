package com.yuewei.plm.module.process.vo;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.module.process.entity.ProcessEntity;
import java.math.BigDecimal;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ProcessOperationMasterVO {

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    private Long processId;
    private String processCode;
    private String processName;
    private String processCategory;
    private String operationType;
    private String operationCraftCode;
    private BigDecimal defaultStandardTimeMins;
    private String defaultQualityRequirement;
    private String defaultProcessParamJson;
    private Boolean needWorkstation;
    private String workstationType;
    private String status;
    private String remark;
    private String updatedAt;

    public static ProcessOperationMasterVO from(ProcessEntity entity) {
        JsonNode metadata = readMetadata(entity.getProcessParamJson());
        return ProcessOperationMasterVO.builder()
            .processId(entity.getProcessId())
            .processCode(entity.getProcessCode())
            .processName(entity.getProcessName())
            .processCategory(text(metadata, "processCategory"))
            .operationType(text(metadata, "operationType"))
            .operationCraftCode(text(metadata, "operationCraftCode"))
            .defaultStandardTimeMins(entity.getStandardTimeMins())
            .defaultQualityRequirement(entity.getQualityRequirement())
            .defaultProcessParamJson(jsonText(metadata, "defaultProcessParamJson"))
            .needWorkstation(booleanValue(metadata, "needWorkstation"))
            .workstationType(text(metadata, "workstationType"))
            .status(entity.getStatus())
            .remark(entity.getRemark())
            .updatedAt(entity.getUpdatedAt() == null ? null : entity.getUpdatedAt().toString())
            .build();
    }

    private static JsonNode readMetadata(String processParamJson) {
        if (processParamJson == null || processParamJson.isBlank()) {
            return OBJECT_MAPPER.createObjectNode();
        }
        try {
            return OBJECT_MAPPER.readTree(processParamJson);
        } catch (Exception ignored) {
            return OBJECT_MAPPER.createObjectNode();
        }
    }

    private static String text(JsonNode node, String field) {
        JsonNode value = node.get(field);
        return value == null || value.isNull() ? null : value.asText();
    }

    private static String jsonText(JsonNode node, String field) {
        JsonNode value = node.get(field);
        return value == null || value.isNull() ? null : value.toString();
    }

    private static Boolean booleanValue(JsonNode node, String field) {
        JsonNode value = node.get(field);
        return value == null || value.isNull() ? Boolean.FALSE : value.asBoolean(false);
    }
}
