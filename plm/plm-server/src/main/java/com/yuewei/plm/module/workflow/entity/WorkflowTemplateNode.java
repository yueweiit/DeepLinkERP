package com.yuewei.plm.module.workflow.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.yuewei.plm.repository.entity.BaseEntity;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@TableName("plm_workflow_template_node")
@EqualsAndHashCode(callSuper = true)
public class WorkflowTemplateNode extends BaseEntity {

    @TableId(value = "workflow_node_id", type = IdType.AUTO)
    private Long workflowNodeId;
    private Long workflowTemplateId;
    private Integer stepNo;
    private String nodeCode;
    private String nodeName;
    private String stageCode;
    private String stageName;
    private String phaseName;
    private Integer requiredAttachment;
    private String requiredFileCategory;
    private String uploadPrompt;
    private String confirmPrompt;
    private String emptyFileMessage;
    private Integer gateFlag;
    private Integer enabledFlag;
    private String remark;
}
