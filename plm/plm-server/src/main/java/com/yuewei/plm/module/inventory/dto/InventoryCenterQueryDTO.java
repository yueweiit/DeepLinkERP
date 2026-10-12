package com.yuewei.plm.module.inventory.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class InventoryCenterQueryDTO {
    @Min(1) @Max(2147483647)
    private long page = 1;
    @Min(1) @Max(100)
    private long size = 50;
    @Size(max = 256)
    private String keyword;
    @Pattern(regexp = "all|material-group:[0-9]{1,18}")
    private String nodeId = "all";
    @Pattern(regexp = "all|7d|30d|90d|this_year")
    private String timeRange = "all";
}
