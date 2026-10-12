package com.yuewei.plm.module.operationlog.repository;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.yuewei.plm.module.operationlog.entity.OperationLog;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface OperationLogRepository extends BaseMapper<OperationLog> {
}
