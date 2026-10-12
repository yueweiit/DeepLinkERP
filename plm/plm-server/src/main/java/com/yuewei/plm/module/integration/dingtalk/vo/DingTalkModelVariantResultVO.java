package com.yuewei.plm.module.integration.dingtalk.vo;

import java.util.List;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class DingTalkModelVariantResultVO {
    private Long integrationRecordId;
    private Long projectId;
    private String dingTalkApprovalNo;
    private String status;
    private boolean idempotentHit;
    private String attachmentArchiveStatus;
    private List<MoldCodeMatchVO> moldMatches;
}
