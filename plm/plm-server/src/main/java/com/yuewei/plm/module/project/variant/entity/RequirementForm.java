package com.yuewei.plm.module.project.variant.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.yuewei.plm.repository.entity.BaseEntity;
import java.time.LocalDate;
import java.time.LocalDateTime;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@TableName("plm_project_requirement_form")
@EqualsAndHashCode(callSuper = true)
public class RequirementForm extends BaseEntity {
    @TableId(value = "requirement_form_id", type = IdType.AUTO)
    private Long requirementFormId;
    private Long projectId;
    private String dingTalkApprovalNo;
    private String networkType;
    private String holeType;
    private String mobileFunction;
    private String tipo;
    private String priority;
    private String manufacturingLocation;
    private String moldMarking;
    private String productSpecificCode;
    private String phoneModelCode;
    private String materialCodes;
    private String moldCodes;
    private String moldMatchStatus;
    private String moldMatchJson;
    private String referenceUrl;
    private String remark;
    private LocalDate expectedDeliveryDate;
    private String requirementType;
    private String customerRequirement;
    private String status;
    private LocalDateTime confirmedAt;
    private String confirmedBy;
}
