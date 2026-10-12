package com.yuewei.plm.module.order.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.yuewei.plm.repository.entity.BaseEntity;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@TableName("plm_order")
@EqualsAndHashCode(callSuper = true)
public class OrderEntity extends BaseEntity {
    @TableId(value = "order_id", type = IdType.AUTO)
    private Long orderId;
    private String orderCode;
    private Long customerId;
    private Long productId;
    private Long projectId;
    private String orderType;
    private String orderSourceType;
    private String orderTitle;
    private BigDecimal quantity;
    private String unit;
    private LocalDate expectedDate;
    private String priorityLevel;
    private String status;
    private String sourceChannel;
    private String requirementContent;
    private Integer customerConfirmedFlag;
    private String dingTalkApprovalNo;
    private String projectType;
    private String phoneModel;
    private String productName;
    private String previousStatus;
    private String closeReason;
    private LocalDateTime closedAt;
    private String closedBy;
    private String sourceAction;
    private String customerRequirement;
    private String sourcePayloadJson;
}

