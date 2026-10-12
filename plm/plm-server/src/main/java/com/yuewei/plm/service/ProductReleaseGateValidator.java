package com.yuewei.plm.service;

import com.yuewei.plm.repository.entity.Product;
import com.yuewei.plm.service.vo.ProductReleaseGateCheckVO;

public interface ProductReleaseGateValidator {

    ProductReleaseGateCheckVO check(Product product);
}
