package com.yuewei.plm.module.bom.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.yuewei.plm.repository.entity.BaseEntity;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@TableName("plm_product_bom_route")
@EqualsAndHashCode(callSuper = true)
public class ProductBomRoute extends BaseEntity {
    @TableId(value = "product_bom_route_id", type = IdType.AUTO)
    private Long productBomRouteId;
    private Long productBomId;
    private Long productId;
    private Long processId;
    private String routeCode;
    private String routeName;
    private String sharedBomGroupCode;
    private String routeVariantNo;
    private String variantName;
    private String variantSourceType;
    private String status;
    private Long sourceProductBomRouteId;
}
