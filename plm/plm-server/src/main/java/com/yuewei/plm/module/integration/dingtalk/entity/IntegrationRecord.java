package com.yuewei.plm.module.integration.dingtalk.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.yuewei.plm.repository.entity.BaseEntity;
import java.time.LocalDateTime;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@TableName("plm_integration_record")
@EqualsAndHashCode(callSuper = true)
public class IntegrationRecord extends BaseEntity {
    @TableId(value = "integration_record_id", type = IdType.AUTO)
    private Long integrationRecordId;
    private String sourceSystem;
    private String integrationType;
    private String externalInstanceId;
    private String externalStatus;
    private String processCode;
    private String direction;
    private String nodeKey;
    private String externalUrl;
    private String sourcePayloadJson;
    private String processingStatus;
    private Long orderId;
    private Long projectId;
    private String errorCode;
    private String errorMessage;
    private Integer retryCount;
    private LocalDateTime lastTriggeredAt;
}
