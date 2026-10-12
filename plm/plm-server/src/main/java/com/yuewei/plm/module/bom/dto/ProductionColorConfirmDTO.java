package com.yuewei.plm.module.bom.dto;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import java.util.List;
import lombok.Data;

@Data
public class ProductionColorConfirmDTO {
    @Valid
    @NotEmpty
    private List<ColorSelection> colors;

    @Data
    public static class ColorSelection {
        @NotNull
        private Long codeItemId;
        @NotBlank
        private String colorCode;
        @NotBlank
        private String colorName;
        @NotNull
        private Long productBomId;
        @NotNull
        private Long productBomRouteId;
    }
}
