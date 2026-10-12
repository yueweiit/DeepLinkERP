package com.yuewei.plm.module.process.vo;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class LinkedBomRouteVO {
    private Long productBomRouteId;
    private Long productBomId;
    private String routeCode;
    private String routeName;
    private String status;
}
