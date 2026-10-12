package com.yuewei.plm.module.bom.vo;

import com.yuewei.plm.module.bom.entity.ProductBomRouteColor;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ProductBomRouteColorVO {
    private Long codeItemId;
    private String codeValue;
    private String codeName;

    public static ProductBomRouteColorVO from(ProductBomRouteColor value) {
        return ProductBomRouteColorVO.builder().codeItemId(value.getCodeItemId())
            .codeValue(value.getColorCode()).codeName(value.getColorName()).build();
    }
}
