package com.yuewei.plm.module.bom.dto;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import java.math.BigDecimal;
import java.util.List;
import lombok.Data;

@Data
public class BomRouteSaveDTO {
    private Long productBomRouteId;
    private Long sourceProductBomRouteId;
    private String sharedBomGroupCode;
    private String routeVariantNo;
    private String variantName;
    @NotNull
    private Long processId;
    @NotBlank
    private String routeCode;
    @NotBlank
    private String routeName;
    @NotEmpty
    private List<@NotBlank String> colors;
    @Valid
    private List<BomRouteColorDTO> colorItems;
    @Valid
    @NotEmpty
    private List<ProductBomItemDTO> items;
    private BigDecimal processCost;
    private BigDecimal packageCost;
    private BigDecimal laborCost;
    private BigDecimal toolingCost;
    private BigDecimal otherCost;
}
