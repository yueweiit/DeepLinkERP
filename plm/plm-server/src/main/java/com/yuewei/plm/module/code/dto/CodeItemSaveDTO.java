package com.yuewei.plm.module.code.dto;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class CodeItemSaveDTO {
    @NotBlank
    @Size(max = 64)
    private String codeType;
    @NotBlank
    @Size(max = 64)
    private String codeValue;
    @NotBlank
    @Size(max = 128)
    private String codeName;
    @Size(max = 128)
    private String codeNameZh;
    @NotNull
    @Min(0)
    private Integer sortOrder;
}
