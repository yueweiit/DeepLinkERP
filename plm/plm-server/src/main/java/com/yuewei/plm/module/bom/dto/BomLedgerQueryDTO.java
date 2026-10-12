package com.yuewei.plm.module.bom.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class BomLedgerQueryDTO {
    @Min(1) @Max(2147483647)
    private long page = 1;
    @Min(1) @Max(200)
    private long size = 50;
    @Size(max = 256)
    private String keyword;
}
