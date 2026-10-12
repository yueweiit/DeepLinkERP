package com.yuewei.plm.module.operationlog.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.yuewei.plm.repository.entity.BaseEntity;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@TableName("plm_operation_log")
@EqualsAndHashCode(callSuper = true)
public class OperationLog extends BaseEntity {

    @TableId(value = "log_id", type = IdType.AUTO)
    private Long logId;
    private String requestId;
    private Long operatorUserId;
    private String operatorUserName;
    private String action;
    private String businessType;
    private String businessId;
    private String businessCode;
    private String businessName;
    private String result;
    private String requestMethod;
    private String requestUri;
    private String clientIp;
    private String userAgent;
    private String detailJson;
}
