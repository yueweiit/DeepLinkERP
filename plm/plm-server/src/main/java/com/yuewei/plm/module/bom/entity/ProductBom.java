package com.yuewei.plm.module.bom.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.yuewei.plm.repository.entity.BaseEntity;
import java.time.LocalDateTime;
import java.math.BigDecimal;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@TableName("plm_product_bom")
@EqualsAndHashCode(callSuper = true)
public class ProductBom extends BaseEntity {

    @TableId(value = "product_bom_id", type = IdType.AUTO)
    private Long productBomId;
    private Long productId;
    private String bomCode;
    private String bomName;
    private String bomType;
    private String versionNo;
    private String status;
    private String bomScope;
    private String sourceType;
    private Long sourceProductId;
    private Long sourceProductBomId;
    private BigDecimal testTotalCost;
    private String currencyCode;
    private LocalDateTime calculatedAt;
    private LocalDateTime confirmedAt;
    private String confirmedBy;
    private Integer frozenFlag;
    private LocalDateTime frozenAt;
    private String frozenBy;
    private LocalDateTime releasedAt;
    private String releasedBy;
    private String remark;
}
