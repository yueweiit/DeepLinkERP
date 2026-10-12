package com.yuewei.plm.module.order.service;

import java.time.LocalDate;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class OrderCreateCommand {
    private Long projectId;
    private Long productId;
    private Long customerId;
    private String dingTalkApprovalNo;
    private String projectType;
    private String phoneModel;
    private String productName;
    private String orderType;
    private String orderTitle;
    private String customerRequirement;
    private String priorityLevel;
    private LocalDate expectedDate;
    private String sourcePayloadJson;
    private String operator;
}

