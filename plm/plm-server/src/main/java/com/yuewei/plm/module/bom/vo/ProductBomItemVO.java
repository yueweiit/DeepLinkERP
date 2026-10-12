package com.yuewei.plm.module.bom.vo;

import com.yuewei.plm.module.bom.entity.ProductBomItem;
import java.math.BigDecimal;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ProductBomItemVO {

    private Long productBomItemId;
    private Long productBomId;
    private Long inventoryId;
    private String itemCode;
    private String itemName;
    private String specification;
    private Integer lineNo;
    private BigDecimal quantity;
    private String unit;
    private BigDecimal lossRate;
    private BigDecimal unitCost;
    private BigDecimal lineCost;
    private String supplierCode;
    private String supplierName;
    private String currencyCode;
    private String materialSource;
    private Integer unmatchedFlag;
    private String lookupMessage;
    private Integer substituteFlag;
    private String remark;
    private String status;

    public static ProductBomItemVO from(ProductBomItem item) {
        return ProductBomItemVO.builder()
            .productBomItemId(item.getProductBomItemId())
            .productBomId(item.getProductBomId())
            .inventoryId(item.getInventoryId())
            .itemCode(item.getItemCode())
            .itemName(item.getItemName())
            .specification(item.getSpecification())
            .lineNo(item.getLineNo())
            .quantity(item.getQuantity())
            .unit(item.getUnit())
            .lossRate(item.getLossRate())
            .unitCost(item.getUnitCostSnapshot())
            .lineCost(item.getLineCostSnapshot())
            .supplierCode(item.getSupplierCodeSnapshot())
            .supplierName(item.getSupplierNameSnapshot())
            .currencyCode(item.getCurrencyCode())
            .materialSource(item.getMaterialSource())
            .unmatchedFlag(item.getUnmatchedFlag())
            .lookupMessage(Integer.valueOf(1).equals(item.getUnmatchedFlag())
                ? "未匹配物料库，可人工录入"
                : null)
            .substituteFlag(item.getSubstituteFlag())
            .remark(item.getRemark())
            .status(item.getStatus())
            .build();
    }
}
