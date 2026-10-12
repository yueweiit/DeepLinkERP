package com.yuewei.plm.module.integration.dingtalk.dto;

import com.fasterxml.jackson.annotation.JsonAlias;
import jakarta.validation.constraints.NotBlank;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;
import lombok.Data;

@Data
public class DingTalkModelVariantReceiveDTO {
    @JsonAlias({"approvalNo", "approval_no", "businessId", "business_id"})
    @NotBlank private String dingTalkApprovalNo;
    @JsonAlias({"approval_instance_id", "processInstanceId", "process_instance_id", "instanceId", "instance_id"})
    private String approvalInstanceId;
    @JsonAlias({"task_id"})
    private String taskId;
    @JsonAlias({"approval_task_id"})
    private String approvalTaskId;
    private String processCode;
    @NotBlank private String approvalStatus;
    private Long parentProductId;
    @NotBlank private String model;
    private String networkType;
    private String holeType;
    private String mobileFunction;
    @NotBlank private String tipo;
    private String priority;
    private String manufacturingLocation;
    private String moldMarking;
    private String productSpecificCode;
    private String phoneModelCode;
    private List<String> materialCodes;
    private String moldCodes;
    private String referenceUrl;
    private String remark;
    private LocalDate expectedDeliveryDate;
    private LocalDateTime sourceApprovedAt;
    private List<DingTalkAttachmentDTO> attachments;
    private String sourcePayloadJson;
    @NotBlank private String createdBy;
}
