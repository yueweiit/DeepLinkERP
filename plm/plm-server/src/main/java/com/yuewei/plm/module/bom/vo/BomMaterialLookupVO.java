package com.yuewei.plm.module.bom.vo;

import com.yuewei.plm.module.bom.service.BomMaterialLookup;
import java.math.BigDecimal;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class BomMaterialLookupVO {
    private boolean matched;
    private Long inventoryId;
    private String inventoryCode;
    private String inventoryName;
    private String specification;
    private String unit;
    private String supplierName;
    private BigDecimal unitCost;
    private String currencyCode;
    private String message;

    public static BomMaterialLookupVO matched(BomMaterialLookup.Material material) {
        return BomMaterialLookupVO.builder()
            .matched(true)
            .inventoryId(material.inventoryId())
            .inventoryCode(material.inventoryCode())
            .inventoryName(material.inventoryName())
            .specification(material.specification())
            .unit(material.unit())
            .supplierName(material.supplierName())
            .unitCost(material.unitCost())
            .currencyCode(material.currencyCode())
            .build();
    }

    public static BomMaterialLookupVO unmatched(String inventoryCode) {
        return BomMaterialLookupVO.builder()
            .matched(false)
            .inventoryCode(inventoryCode)
            .message("物料编码未匹配到物料库，可先人工录入候选 BOM，正式发布前请确认物料资料。")
            .build();
    }
}
