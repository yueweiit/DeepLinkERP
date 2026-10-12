package com.yuewei.plm.module.integration.dingtalk.vo;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class DingTalkProductLineResultVO {
    private Long integrationRecordId;
    private Long projectId;
    private String productCode;
    private String productName;
    private String productType;
    private String dingTalkApprovalNo;
    private String status;
    private boolean idempotentHit;
    private String attachmentArchiveStatus;
}
