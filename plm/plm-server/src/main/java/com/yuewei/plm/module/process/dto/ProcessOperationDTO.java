package com.yuewei.plm.module.process.dto;

import jakarta.validation.constraints.NotNull;
import java.math.BigDecimal;
import lombok.Data;

@Data
public class ProcessOperationDTO {

    @NotNull(message = "工序顺序不能为空")
    private Integer sequenceNo;

    private Long operationMasterProcessId;
    private String operationSource;

    private String processName;

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
    private String processParamJson;
    private BigDecimal standardTimeMins;

    private String qualityRequirement;

    private String remark;
}
