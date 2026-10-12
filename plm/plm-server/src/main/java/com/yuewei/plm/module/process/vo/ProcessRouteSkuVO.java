package com.yuewei.plm.module.process.vo;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ProcessRouteSkuVO {
    private Long productId;
    private String skuCode;
    private String productName;
    private String phoneModel;
    private String phoneModelCode;
    private String color;
    private String colorCode;
    private String finishedProductCode;
    private String status;
    private Long productBomRouteId;
    private String routeCode;
    private String routeName;
}
