package com.yuewei.plm.module.code.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import lombok.Data;

@Data
public class CodeItemQueryDTO {
    private String codeType = "color";
    private String keyword;
    private String status;
    @Min(1)
    private long page = 1;
    @Min(1)
    @Max(200)
    private long size = 20;
}
