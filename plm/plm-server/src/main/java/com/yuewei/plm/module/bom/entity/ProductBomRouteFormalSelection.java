package com.yuewei.plm.module.bom.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.yuewei.plm.repository.entity.BaseEntity;
import java.time.LocalDateTime;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@TableName("plm_product_bom_route_formal_selection")
@EqualsAndHashCode(callSuper = true)
public class ProductBomRouteFormalSelection extends BaseEntity {
    @TableId(value = "product_bom_route_formal_selection_id", type = IdType.AUTO)
    private Long productBomRouteFormalSelectionId;
    private Long productId;
    private Long productBomId;
    private Long productBomRouteId;
    private Long processId;
    private String bomVersionNo;
    private String selectionBatchNo;
    private String status;
    private LocalDateTime confirmedAt;
    private String confirmedBy;
    private LocalDateTime invalidatedAt;
    private String invalidatedReason;
    private String remark;
}
