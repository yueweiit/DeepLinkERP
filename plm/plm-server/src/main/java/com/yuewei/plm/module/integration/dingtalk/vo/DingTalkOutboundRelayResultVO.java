package com.yuewei.plm.module.integration.dingtalk.vo;

import lombok.Builder;
import lombok.Data;

@Data
@Builder(toBuilder = true)
public class DingTalkOutboundRelayResultVO {
    private String status;
    private String action;
    private String approvalInstanceId;
    private String processInstanceId;
    private String taskId;
    private String externalStatus;
    private String errorCode;
    private String message;
}
