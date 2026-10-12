package com.yuewei.plm.module.workflow.repository;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.yuewei.plm.module.workflow.entity.WorkflowTemplate;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface WorkflowTemplateRepository extends BaseMapper<WorkflowTemplate> {
}
