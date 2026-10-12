package com.yuewei.plm.module.bom.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.yuewei.plm.repository.entity.BaseEntity;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@TableName("plm_product_bom_route_color")
@EqualsAndHashCode(callSuper = true)
public class ProductBomRouteColor extends BaseEntity {
    @TableId(value = "product_bom_route_color_id", type = IdType.AUTO)
    private Long productBomRouteColorId;
    private Long productBomId;
    private Long productBomRouteId;
    private Long codeItemId;
    private String colorCode;
    private String colorName;
    private String status;
}
