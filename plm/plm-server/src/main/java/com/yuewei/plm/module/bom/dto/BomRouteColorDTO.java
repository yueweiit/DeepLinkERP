package com.yuewei.plm.module.bom.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

@Data
public class BomRouteColorDTO {
    @NotNull
    private Long codeItemId;
    @NotBlank
    private String codeValue;
    @NotBlank
    private String codeName;
}
