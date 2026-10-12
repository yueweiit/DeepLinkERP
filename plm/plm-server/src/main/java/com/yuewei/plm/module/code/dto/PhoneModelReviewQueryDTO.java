package com.yuewei.plm.module.code.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class PhoneModelReviewQueryDTO {
    @Pattern(regexp = "code_many_names|name_many_codes")
    private String kind = "code_many_names";
    @Min(1) @Max(2147483647)
    private long page = 1;
    @Min(1) @Max(100)
    private long size = 50;
    @Size(max = 256)
    private String keyword;
}
