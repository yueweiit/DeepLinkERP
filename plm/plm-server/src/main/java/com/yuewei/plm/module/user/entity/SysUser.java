package com.yuewei.plm.module.user.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.yuewei.plm.repository.entity.BaseEntity;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@TableName("sys_user")
@EqualsAndHashCode(callSuper = true)
public class SysUser extends BaseEntity {

    @TableId(value = "user_id", type = IdType.AUTO)
    private Long userId;
    private String username;
    private String passwordHash;
    private String displayName;
    private String departmentName;
    private Integer formalFlag;
    private Boolean allPermissions;
    private String status;
}
