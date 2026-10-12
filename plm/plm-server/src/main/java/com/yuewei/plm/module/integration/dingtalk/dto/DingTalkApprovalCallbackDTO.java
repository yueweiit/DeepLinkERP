package com.yuewei.plm.module.integration.dingtalk.dto;

import com.fasterxml.jackson.annotation.JsonAlias;
import jakarta.validation.constraints.NotBlank;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import lombok.Data;

@Data
public class DingTalkApprovalCallbackDTO {
    @NotBlank
    private String processCode;
    @JsonAlias({"approval_instance_id", "processInstanceId", "process_instance_id", "instanceId", "instance_id"})
    private String approvalInstanceId;
    @JsonAlias({"dingTalkApprovalNo", "approval_no", "businessId", "business_id"})
    private String approvalNo;
    @JsonAlias({"task_id"})
    private String taskId;
    @JsonAlias({"approval_task_id"})
    private String approvalTaskId;
    @NotBlank
    private String approvalStatus;
    private OffsetDateTime approvedAt;
    private String formUrl;
    private Applicant applicant;
    private Map<String, Object> form;
    private List<DingTalkAttachmentDTO> attachments;
    private String sourcePayloadJson;

    private String userId;
    private String userName;
    private String departmentName;
    private Long parentProductId;
    private String tipo;
    private String model;
    private String moldMarking;
    private String moldCodes;
    private String generatedCode;
    private String expectedDeliveryDate;
    private String productName;
    private String productCodePrefix;
    private String moldCodePrefix;
    private Object productionColors;
    private Object moldMaterials;
    private String remark;

    @Data
    public static class Applicant {
        private String userId;
        private String userName;
        private String departmentName;
    }
}
