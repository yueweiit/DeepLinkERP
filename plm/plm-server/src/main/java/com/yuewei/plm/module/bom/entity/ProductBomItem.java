package com.yuewei.plm.module.bom.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.yuewei.plm.repository.entity.BaseEntity;
import java.math.BigDecimal;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@TableName("plm_product_bom_item")
@EqualsAndHashCode(callSuper = true)
public class ProductBomItem extends BaseEntity {

    @TableId(value = "product_bom_item_id", type = IdType.AUTO)
    private Long productBomItemId;
    private Long productBomId;
    private Long productBomRouteId;
    private Long productId;
    private String sharedBomGroupCode;
    private Long inventoryId;
    private String itemCode;
    private String itemName;
    private String specification;
    private Integer lineNo;
    private BigDecimal quantity;
    @TableField("uom_code")
    private String unit;
    private BigDecimal lossRate;
    private BigDecimal unitCostSnapshot;
    private String supplierCodeSnapshot;
    private String supplierNameSnapshot;
    private BigDecimal lineCostSnapshot;
    private String currencyCode;
    private String materialSource;
    private Integer unmatchedFlag;
    private Integer substituteFlag;
    private String remark;
    private String versionNo;
    private String status;
}
