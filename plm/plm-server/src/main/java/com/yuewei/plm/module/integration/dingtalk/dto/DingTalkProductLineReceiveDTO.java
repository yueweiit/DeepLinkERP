package com.yuewei.plm.module.integration.dingtalk.dto;

import jakarta.validation.constraints.NotBlank;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;
import lombok.Data;

@Data
public class DingTalkProductLineReceiveDTO {
    @NotBlank
    private String approvalInstanceId;
    private String taskId;
    private String approvalTaskId;
    private String approvalNo;
    private String processCode;
    @NotBlank
    private String approvalStatus;
    @NotBlank
    private String productName;
    private String productCodePrefix;
    private String moldCodePrefix;
    private String productionColors;
    private String moldMaterials;
    private LocalDate expectedDeliveryDate;
    private LocalDateTime sourceApprovedAt;
    private String formUrl;
    private String applicantUserId;
    private String applicantUserName;
    private String applicantDepartmentName;
    private String remark;
    private List<DingTalkAttachmentDTO> attachments;
    private String sourcePayloadJson;
}
