package com.yuewei.plm.module.bom.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.yuewei.plm.common.mybatis.typehandler.PostgresJsonbStringTypeHandler;
import com.yuewei.plm.repository.entity.BaseEntity;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@TableName(value = "plm_product_bom_cost_snapshot", autoResultMap = true)
@EqualsAndHashCode(callSuper = true)
public class ProductBomCostSnapshot extends BaseEntity {
    @TableId(value = "product_bom_cost_snapshot_id", type = IdType.AUTO)
    private Long productBomCostSnapshotId;
    private Long productBomId;
    private Long productBomRouteId;
    private Long productId;
    private String versionNo;
    private BigDecimal materialCost;
    private BigDecimal lossCost;
    private BigDecimal processCost;
    private BigDecimal packageCost;
    private BigDecimal laborCost;
    private BigDecimal toolingCost;
    private BigDecimal otherCost;
    private BigDecimal totalCost;
    private String currencyCode;
    @TableField(typeHandler = PostgresJsonbStringTypeHandler.class)
    private String sourceSnapshotJson;
    private LocalDateTime calculatedAt;
    private String status;
}
