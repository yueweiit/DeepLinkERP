package com.yuewei.plm.module.order.repository;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.yuewei.plm.module.order.entity.OrderEntity;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface OrderRepository extends BaseMapper<OrderEntity> {
}

