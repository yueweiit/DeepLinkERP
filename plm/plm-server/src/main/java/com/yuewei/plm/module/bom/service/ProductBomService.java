package com.yuewei.plm.module.bom.service;

import com.yuewei.plm.module.bom.dto.ProductBomCreateDTO;
import com.yuewei.plm.module.bom.dto.ProductBomItemDTO;
import com.yuewei.plm.module.bom.dto.ProductBomUpdateDTO;
import com.yuewei.plm.module.bom.vo.ProductBomVO;
import jakarta.servlet.http.HttpServletRequest;
import java.util.List;

public interface ProductBomService {

    List<ProductBomVO> listByProject(Long projectId);

    ProductBomVO getById(Long bomId);

    ProductBomVO create(Long projectId, ProductBomCreateDTO dto, HttpServletRequest request);

    ProductBomVO update(Long bomId, ProductBomUpdateDTO dto, HttpServletRequest request);

    ProductBomVO addItem(Long bomId, ProductBomItemDTO dto, HttpServletRequest request);

    ProductBomVO updateItem(Long bomId, Long itemId, ProductBomItemDTO dto, HttpServletRequest request);

    ProductBomVO deleteItem(Long bomId, Long itemId, HttpServletRequest request);

    void deleteVersion(Long bomId, HttpServletRequest request);

    ProductBomVO freeze(Long bomId, HttpServletRequest request);

    ProductBomVO confirmCurrentVersion(Long bomId, HttpServletRequest request);

    ProductBomVO cancelCurrentConfirmation(Long bomId, HttpServletRequest request);
}
