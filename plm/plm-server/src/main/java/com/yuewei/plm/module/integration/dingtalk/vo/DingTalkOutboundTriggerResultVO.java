package com.yuewei.plm.module.integration.dingtalk.vo;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class DingTalkOutboundTriggerResultVO {
    private Long integrationRecordId;
    private Long projectId;
    private String nodeKey;
    private String externalInstanceId;
    private String externalUrl;
    private String status;
    private boolean idempotentHit;
}
