package com.yuewei.plm.module.project.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import lombok.Data;

@Data
public class ProjectQueryDTO {

    @Min(value = 1, message = "页码最小为1")
    private long page = 1;

    @Min(value = 1, message = "每页最小为1")
    @Max(value = 200, message = "每页最大为200")
    private long size = 20;

    private String keyword;
    private String productType;
    private String status;
    private Long ownerUserId;
}
