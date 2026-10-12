package com.yuewei.plm.module.order.vo;

import java.time.LocalDateTime;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class OrderVO {
    private Long orderId;
    private String dingTalkApprovalNo;
    private String orderCode;
    private String phoneModel;
    private String projectType;
    private String orderType;
    private String productName;
    private String status;
    private Long projectId;
    private String closeReason;
    private LocalDateTime createdAt;
}

