package com.yuewei.plm.module.user.repository;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.yuewei.plm.module.user.entity.SysUser;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface SysUserRepository extends BaseMapper<SysUser> {
}
