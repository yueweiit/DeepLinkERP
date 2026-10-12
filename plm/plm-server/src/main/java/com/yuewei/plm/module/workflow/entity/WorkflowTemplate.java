package com.yuewei.plm.module.workflow.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.yuewei.plm.repository.entity.BaseEntity;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@TableName("plm_workflow_template")
@EqualsAndHashCode(callSuper = true)
public class WorkflowTemplate extends BaseEntity {

    @TableId(value = "workflow_template_id", type = IdType.AUTO)
    private Long workflowTemplateId;
    private String flowType;
    private String templateName;
    private String versionNo;
    private String status;
    private Integer activeFlag;
    private String description;
}
