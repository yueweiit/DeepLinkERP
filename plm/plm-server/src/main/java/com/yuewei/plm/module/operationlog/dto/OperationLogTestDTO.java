package com.yuewei.plm.module.operationlog.dto;

import jakarta.validation.constraints.NotBlank;
import java.util.Map;
import lombok.Data;

@Data
public class OperationLogTestDTO {

    @NotBlank(message = "业务类型不能为空")
    private String businessType;

    private String businessId;
    private String businessCode;
    private String businessName;
    private Map<String, Object> detail;
}
