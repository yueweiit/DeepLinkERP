package com.yuewei.plm.repository;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.yuewei.plm.repository.entity.Product;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface ProductRepository extends BaseMapper<Product> {
}
