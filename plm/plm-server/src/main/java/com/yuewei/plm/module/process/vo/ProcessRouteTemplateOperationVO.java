package com.yuewei.plm.module.process.vo;

import java.math.BigDecimal;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ProcessRouteTemplateOperationVO {

    private String operationCode;
    private Long operationMasterProcessId;
    private String operationCraftCode;
    private String materialStatusCode;
    private Boolean finishedProductFlag;
    private String businessOperationCode;
    private Boolean businessOperationCodeManualFlag;
    private Integer sequenceNo;
    private String processName;
    private String processParamJson;
    private BigDecimal standardTimeMins;
    private String qualityRequirement;
    private String remark;
}
