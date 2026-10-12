package com.yuewei.plm.controller.dto;

import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class ProductLifecycleActionDTO {

    @Size(max = 1000, message = "原因不能超过1000个字符")
    private String reason;

    private Boolean riskConfirmed;
}
