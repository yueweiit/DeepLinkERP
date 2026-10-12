package com.yuewei.plm.service;

import com.yuewei.plm.common.vo.PageVO;
import com.yuewei.plm.controller.dto.ProductCreateDTO;
import com.yuewei.plm.controller.dto.ProductLifecycleActionDTO;
import com.yuewei.plm.controller.dto.ProductQueryDTO;
import com.yuewei.plm.controller.dto.ProductUpdateDTO;
import com.yuewei.plm.service.vo.ProductCreateResultVO;
import com.yuewei.plm.service.vo.ProductProductionColorVO;
import com.yuewei.plm.service.vo.ProductReleaseGateCheckVO;
import com.yuewei.plm.service.vo.ProductVO;
import jakarta.servlet.http.HttpServletRequest;
import java.util.List;

public interface ProductService {

    PageVO<ProductVO> page(ProductQueryDTO queryDTO);

    ProductVO getById(Long productId);

    List<ProductProductionColorVO> listProductionColors(Long productId);

    ProductCreateResultVO create(ProductCreateDTO createDTO);

    ProductVO update(Long productId, ProductUpdateDTO updateDTO);

    ProductVO updateBasicInfo(Long productId, ProductUpdateDTO updateDTO);

    void freeze(Long productId, String reason, HttpServletRequest request);

    void publish(Long productId, String operator);

    ProductReleaseGateCheckVO checkReleaseGate(Long productId);

    ProductVO freeze(Long productId, ProductLifecycleActionDTO dto, HttpServletRequest request);

    ProductVO publish(Long productId, ProductLifecycleActionDTO dto, HttpServletRequest request);

    ProductVO archive(Long productId, ProductLifecycleActionDTO dto, HttpServletRequest request);

    ProductVO abandon(Long productId, ProductLifecycleActionDTO dto, HttpServletRequest request);
}
