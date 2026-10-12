package com.yuewei.plm.controller.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import lombok.Data;

@Data
public class ProductQueryDTO {

    @Min(value = 1, message = "页码最小为1")
    private long page = 1;

    @Min(value = 1, message = "每页最小为1")
    @Max(value = 200, message = "每页最大为200")
    private long size = 20;

    private String keyword;
    private String status;
    private String productType;
    private Long customerId;
    private Long parentProductId;
}
