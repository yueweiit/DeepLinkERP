package com.yuewei.plm.module.integration.dingtalk.repository;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.yuewei.plm.module.integration.dingtalk.entity.IntegrationRecord;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface IntegrationRecordRepository extends BaseMapper<IntegrationRecord> {}
