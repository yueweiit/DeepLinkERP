package com.yuewei.plm.module.product.mold.vo;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ProductMoldCodeVO {
    private Long productMoldCodeId;
    private Long productId;
    private String moldCode;
    private String moldPrefix;
    private String productCodePrefix;
    private String productSpecificCode;
    private String moldName;
    private String keyCode;
    private Long inventoryId;
    private String inventoryStatus;
    private String sourceFile;
    private Integer sourceRowNo;
    private String status;
}
