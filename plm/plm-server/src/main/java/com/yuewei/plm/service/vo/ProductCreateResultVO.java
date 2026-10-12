package com.yuewei.plm.service.vo;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ProductCreateResultVO {
    private Long productId;
    private String productCode;
    private String versionNo;
    private String status;
}
