package com.yuewei.plm.module.order.service;

import com.yuewei.plm.common.vo.PageVO;
import com.yuewei.plm.module.order.dto.OrderQueryDTO;
import com.yuewei.plm.module.order.entity.OrderEntity;
import com.yuewei.plm.module.order.vo.OrderVO;

public interface OrderService {
    PageVO<OrderVO> page(OrderQueryDTO queryDTO);
    OrderEntity create(OrderCreateCommand command);
    OrderEntity findByProjectId(Long projectId);
    OrderEntity findByDingTalkApprovalNo(String approvalNo);
    void markInProduction(Long projectId, String operator);
    void completeByProject(Long projectId, String operator);
    void closeByProject(Long projectId, String reason, String operator);
    void restoreByProject(Long projectId, String operator);
}

