package com.yuewei.plm.module.bom.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.yuewei.plm.repository.entity.BaseEntity;
import java.time.LocalDateTime;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@TableName("plm_product_bom_import_batch")
@EqualsAndHashCode(callSuper = true)
public class ProductBomImportBatch extends BaseEntity {
    @TableId(value = "product_bom_import_batch_id", type = IdType.AUTO)
    private Long productBomImportBatchId;
    private Long productId;
    private Long productBomId;
    private String importToken;
    private String bomScope;
    private String fileName;
    private String status;
    private Integer totalRows;
    private Integer validRows;
    private Integer errorRows;
    private String previewJson;
    private String errorJson;
    private LocalDateTime expiresAt;
    private LocalDateTime committedAt;
    private String committedBy;
}
