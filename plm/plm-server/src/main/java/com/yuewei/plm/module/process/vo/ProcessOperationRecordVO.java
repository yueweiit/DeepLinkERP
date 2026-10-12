package com.yuewei.plm.module.process.vo;

import java.math.BigDecimal;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ProcessOperationRecordVO {
    private Long operationId;
    private String operationCode;
    private Integer sequenceNo;
    private String operationName;
    private String operationType;
    private String workstationName;
    private String supplierName;
    private String parameterSummary;
    private String qualityRequirement;
    private BigDecimal unitCost;
    private Integer leadDays;
    private String attachmentStatus;
    private Boolean isKeyProcess;
    private Boolean isExternalOperation;
    private Boolean isDifferenceOperation;
    private Boolean changedInCurrentVersion;
    private String confirmerName;
    private String confirmerRole;
}
