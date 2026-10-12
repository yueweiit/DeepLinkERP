package com.yuewei.plm.module.process.dto;

import jakarta.validation.constraints.NotBlank;
import java.math.BigDecimal;
import lombok.Data;

@Data
public class ProcessOperationMasterSaveDTO {

    @NotBlank(message = "工序编码不能为空")
    private String processCode;

    @NotBlank(message = "工序名称不能为空")
    private String processName;

    @NotBlank(message = "工序分类不能为空")
    private String processCategory;

    @NotBlank(message = "工序类型不能为空")
    private String operationType;

    private String operationCraftCode;
    private BigDecimal defaultStandardTimeMins;
    private String defaultQualityRequirement;
    private String defaultProcessParamJson;
    private Boolean needWorkstation;
    private String workstationType;
    private String remark;
}
