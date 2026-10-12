package com.yuewei.plm.module.process.repository;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.yuewei.plm.module.process.entity.ProcessEntity;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface ProcessRepository extends BaseMapper<ProcessEntity> {
}
