package com.yuewei.plm.module.integration.dingtalk.dto;

import java.util.List;
import lombok.Data;

@Data
public class DingTalkOutboundRelayDTO {
    private String action;
    private Long projectId;
    private String projectCode;
    private String projectName;
    private String productType;
    private String model;
    private String nodeKey;
    private String nodeName;
    private String sourceApprovalInstanceId;
    private String processCode;
    private String processInstanceId;
    private String approvalInstanceId;
    private String taskId;
    private String actionerUserId;
    private String result;
    private String remark;
    private List<String> receiverUserIds;
}
