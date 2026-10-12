package com.yuewei.plm.module.project.variant.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.yuewei.plm.repository.entity.BaseEntity;
import java.time.LocalDateTime;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@TableName("plm_product_variant_color")
@EqualsAndHashCode(callSuper = true)
public class ProductVariantColor extends BaseEntity {
    @TableId(value = "variant_color_id", type = IdType.AUTO)
    private Long variantColorId;
    private Long projectProductId;
    private Long sourceProductId;
    private Long sourceDecisionId;
    private Long codeItemId;
    private String colorCode;
    private String colorName;
    private String sourceDecisionBatchNo;
    private LocalDateTime sourceConfirmedAt;
    private Integer defaultSelectedFlag;
    private Integer selectedFlag;
    private LocalDateTime deselectedAt;
    private String deselectedBy;
    private String snapshotStatus;
}
