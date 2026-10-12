package com.yuewei.plm.repository.entity;

import com.baomidou.mybatisplus.annotation.TableField;
import java.time.LocalDateTime;
import lombok.Data;

@Data
public abstract class BaseEntity {

    @TableField("created_at")
    private LocalDateTime createdAt;

    @TableField("created_by")
    private String createdBy;

    @TableField("updated_at")
    private LocalDateTime updatedAt;

    @TableField("updated_by")
    private String updatedBy;

    @TableField("deleted_flag")
    private Integer deletedFlag;
}
