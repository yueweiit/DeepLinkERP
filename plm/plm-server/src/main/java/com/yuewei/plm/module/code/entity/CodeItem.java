package com.yuewei.plm.module.code.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.yuewei.plm.repository.entity.BaseEntity;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@TableName("plm_code_item")
@EqualsAndHashCode(callSuper = true)
public class CodeItem extends BaseEntity {
    @TableId(value = "code_item_id", type = IdType.AUTO)
    private Long codeItemId;
    private String codeType;
    private String codeValue;
    private String codeName;
    private String codeNameZh;
    private String status;
    private Integer sortOrder;
}
