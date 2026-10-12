package com.yuewei.plm.module.bom.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.yuewei.plm.repository.entity.BaseEntity;
import java.time.LocalDateTime;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@TableName("plm_product_production_color_decision")
@EqualsAndHashCode(callSuper = true)
public class ProductProductionColorDecision extends BaseEntity {
    @TableId(value = "product_production_color_decision_id", type = IdType.AUTO)
    private Long productProductionColorDecisionId;
    private Long productId;
    private Long codeItemId;
    private String colorCode;
    private String colorName;
    private Long productBomId;
    private Long productBomRouteId;
    private String decisionBatchNo;
    private Integer selectedFlag;
    private String status;
    private Long createdSkuProductId;
    private LocalDateTime confirmedAt;
    private String confirmedBy;
}
