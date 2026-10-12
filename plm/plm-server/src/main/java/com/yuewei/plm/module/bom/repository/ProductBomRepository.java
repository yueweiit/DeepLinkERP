package com.yuewei.plm.module.bom.repository;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.yuewei.plm.module.bom.entity.ProductBom;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface ProductBomRepository extends BaseMapper<ProductBom> {
}
