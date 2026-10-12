package com.yuewei.plm.module.order.dto;

import lombok.Data;

@Data
public class OrderQueryDTO {
    private long page = 1;
    private long size = 20;
    private String keyword;
    private String status;
    private String source;
}

