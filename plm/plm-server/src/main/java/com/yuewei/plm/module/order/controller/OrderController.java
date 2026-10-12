package com.yuewei.plm.module.order.controller;

import com.yuewei.plm.common.constant.ApiConstants;
import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.PageVO;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.order.dto.OrderQueryDTO;
import com.yuewei.plm.module.order.service.OrderService;
import com.yuewei.plm.module.order.vo.OrderVO;
import jakarta.servlet.http.HttpServletRequest;
import java.time.OffsetDateTime;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
@RequestMapping(ApiConstants.API_V1_PREFIX + "/orders")
public class OrderController {
    private final OrderService orderService;

    @GetMapping
    public ResponseVO<PageVO<OrderVO>> page(OrderQueryDTO queryDTO, HttpServletRequest request) {
        return ResponseVO.success(orderService.page(queryDTO), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }
}
