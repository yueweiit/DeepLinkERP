package com.yuewei.plm.module.bom.dto;

import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import java.util.List;
import lombok.Data;

@Data
public class ProductionOperationConfirmDTO {
    @NotNull
    private Long productBomRouteId;
    @NotEmpty
    private List<Long> operationProcessIds;
}
