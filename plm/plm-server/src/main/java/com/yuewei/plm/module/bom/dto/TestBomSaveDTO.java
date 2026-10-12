package com.yuewei.plm.module.bom.dto;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import java.util.List;
import lombok.Data;

@Data
public class TestBomSaveDTO {
    @NotBlank
    private String versionNo;
    @Valid
    @NotEmpty
    private List<ProductBomItemDTO> items;
}
