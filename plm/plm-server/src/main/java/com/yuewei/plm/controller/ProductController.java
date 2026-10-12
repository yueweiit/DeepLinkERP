package com.yuewei.plm.controller;

import com.yuewei.plm.common.constant.ApiConstants;
import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.PageVO;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.controller.dto.ProductCreateDTO;
import com.yuewei.plm.controller.dto.ProductLifecycleActionDTO;
import com.yuewei.plm.controller.dto.ProductQueryDTO;
import com.yuewei.plm.controller.dto.ProductUpdateDTO;
import com.yuewei.plm.service.ProductService;
import com.yuewei.plm.service.vo.ProductCreateResultVO;
import com.yuewei.plm.service.vo.ProductProductionColorVO;
import com.yuewei.plm.service.vo.ProductVO;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import java.time.OffsetDateTime;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
@RequestMapping(ApiConstants.API_V1_PREFIX + "/products")
public class ProductController {

    private final ProductService productService;

    @GetMapping
    @Operation(summary = "产品列表")
    public ResponseVO<PageVO<ProductVO>> list(@Valid ProductQueryDTO queryDTO, HttpServletRequest request) {
        return ResponseVO.success(productService.page(queryDTO), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @GetMapping("/{id}")
    @Operation(summary = "产品详情")
    public ResponseVO<ProductVO> detail(@PathVariable("id") Long productId, HttpServletRequest request) {
        return ResponseVO.success(productService.getById(productId), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @GetMapping("/{id}/production-colors")
    @Operation(summary = "产品已敲定正式投产颜色")
    public ResponseVO<List<ProductProductionColorVO>> productionColors(@PathVariable("id") Long productId,
                                                                       HttpServletRequest request) {
        return ResponseVO.success(productService.listProductionColors(productId), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping
    @Operation(summary = "新建产品")
    public ResponseVO<ProductCreateResultVO> create(@Valid @RequestBody ProductCreateDTO createDTO, HttpServletRequest request) {
        return ResponseVO.created(productService.create(createDTO), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PutMapping("/{id}")
    @Operation(summary = "更新产品")
    public ResponseVO<ProductVO> update(@PathVariable("id") Long productId,
                                        @Valid @RequestBody ProductUpdateDTO updateDTO,
                                        HttpServletRequest request) {
        return ResponseVO.success(productService.update(productId, updateDTO), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PatchMapping("/{id}/basic-info")
    @Operation(summary = "更新产品基础信息")
    public ResponseVO<ProductVO> updateBasicInfo(@PathVariable("id") Long productId,
                                                 @Valid @RequestBody ProductUpdateDTO updateDTO,
                                                 HttpServletRequest request) {
        return ResponseVO.success(productService.updateBasicInfo(productId, updateDTO), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/{id}/freeze")
    @Operation(summary = "冻结产品版本")
    public ResponseVO<Void> freeze(@PathVariable("id") Long productId,
                                   @RequestParam(value = "reason", required = false) String reason,
                                   HttpServletRequest request) {
        productService.freeze(productId, reason, request);
        return ResponseVO.success(RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/{id}/publish")
    @Operation(summary = "发布产品版本")
    public ResponseVO<ProductVO> publish(@PathVariable("id") Long productId,
                                         @RequestBody(required = false) ProductLifecycleActionDTO dto,
                                         HttpServletRequest request) {
        return ResponseVO.success(productService.publish(productId, dto, request), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }
}
