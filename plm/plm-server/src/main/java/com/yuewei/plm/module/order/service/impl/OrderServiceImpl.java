package com.yuewei.plm.module.order.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.vo.PageVO;
import com.yuewei.plm.module.operationlog.service.OperationLogCreateCommand;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.order.dto.OrderQueryDTO;
import com.yuewei.plm.module.order.entity.OrderEntity;
import com.yuewei.plm.module.order.repository.OrderRepository;
import com.yuewei.plm.module.order.service.OrderCreateCommand;
import com.yuewei.plm.module.order.service.OrderService;
import com.yuewei.plm.module.order.vo.OrderVO;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ThreadLocalRandom;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

@Service
@RequiredArgsConstructor
public class OrderServiceImpl implements OrderService {
    private final OrderRepository repository;
    private final OperationLogService operationLogService;

    @Override
    public PageVO<OrderVO> page(OrderQueryDTO queryDTO) {
        List<OrderEntity> values = safe(repository.selectList(new LambdaQueryWrapper<OrderEntity>()
            .eq(StringUtils.hasText(queryDTO.getStatus()), OrderEntity::getStatus, queryDTO.getStatus())
            .eq(StringUtils.hasText(queryDTO.getSource()), OrderEntity::getOrderSourceType, queryDTO.getSource())
            .eq(OrderEntity::getDeletedFlag, 0)
            .orderByDesc(OrderEntity::getCreatedAt)));
        String keyword = clean(queryDTO.getKeyword()).toLowerCase(Locale.ROOT);
        List<OrderVO> filtered = values.stream()
            .filter(value -> keyword.isEmpty() || contains(value.getDingTalkApprovalNo(), keyword)
                || contains(value.getOrderCode(), keyword) || contains(value.getPhoneModel(), keyword)
                || contains(value.getProductName(), keyword) || contains(value.getOrderType(), keyword))
            .map(this::toVO).toList();
        int from = (int) Math.min(filtered.size(), Math.max(0, (queryDTO.getPage() - 1) * queryDTO.getSize()));
        int to = (int) Math.min(filtered.size(), from + queryDTO.getSize());
        long pages = queryDTO.getSize() == 0 ? 0 : (filtered.size() + queryDTO.getSize() - 1) / queryDTO.getSize();
        return PageVO.<OrderVO>builder().content(filtered.subList(from, to)).page(queryDTO.getPage())
            .size(queryDTO.getSize()).totalElements(filtered.size()).totalPages(pages).build();
    }

    @Override
    @Transactional
    public OrderEntity create(OrderCreateCommand command) {
        OrderEntity existing = findByDingTalkApprovalNo(command.getDingTalkApprovalNo());
        if (existing != null) return existing;
        LocalDateTime now = LocalDateTime.now();
        String operator = StringUtils.hasText(command.getOperator()) ? command.getOperator() : "system";
        OrderEntity value = new OrderEntity();
        value.setOrderCode(generateOrderCode());
        value.setCustomerId(command.getCustomerId());
        value.setProductId(command.getProductId());
        value.setProjectId(command.getProjectId());
        value.setDingTalkApprovalNo(command.getDingTalkApprovalNo());
        value.setProjectType(command.getProjectType());
        value.setPhoneModel(command.getPhoneModel());
        value.setProductName(command.getProductName());
        value.setOrderType(command.getOrderType());
        value.setOrderSourceType("customer_requirement".equals(command.getOrderType()) ? "customer" : "market");
        value.setOrderTitle(command.getOrderTitle());
        value.setCustomerRequirement(command.getCustomerRequirement());
        value.setRequirementContent(command.getCustomerRequirement());
        value.setPriorityLevel(command.getPriorityLevel());
        value.setExpectedDate(command.getExpectedDate());
        value.setStatus("confirmed");
        value.setSourceChannel("dingtalk");
        value.setSourcePayloadJson(command.getSourcePayloadJson());
        value.setCustomerConfirmedFlag(0);
        value.setCreatedAt(now); value.setCreatedBy(operator); value.setUpdatedAt(now); value.setUpdatedBy(operator); value.setDeletedFlag(0);
        repository.insert(value);
        log("ORDER_CREATE", value, "{\"source\":\"dingtalk\"}");
        return value;
    }

    @Override public OrderEntity findByProjectId(Long projectId) { return first(repository.selectList(new LambdaQueryWrapper<OrderEntity>().eq(OrderEntity::getProjectId, projectId).eq(OrderEntity::getDeletedFlag, 0))); }
    @Override public OrderEntity findByDingTalkApprovalNo(String approvalNo) { return StringUtils.hasText(approvalNo) ? first(repository.selectList(new LambdaQueryWrapper<OrderEntity>().eq(OrderEntity::getDingTalkApprovalNo, approvalNo).eq(OrderEntity::getDeletedFlag, 0))) : null; }
    @Override @Transactional public void markInProduction(Long projectId, String operator) { updateStatus(projectId, "in_production", operator, null); }
    @Override @Transactional public void completeByProject(Long projectId, String operator) { updateStatus(projectId, "completed", operator, null); }

    @Override
    @Transactional
    public void closeByProject(Long projectId, String reason, String operator) {
        OrderEntity value = findByProjectId(projectId);
        if (value == null) return;
        value.setPreviousStatus(value.getStatus());
        value.setStatus("closed");
        value.setCloseReason(reason);
        value.setClosedAt(LocalDateTime.now());
        value.setClosedBy(operator);
        value.setSourceAction("project_abandoned");
        touch(value, operator);
        repository.updateById(value);
        log("ORDER_CLOSE_BY_PROJECT", value, "{\"reason\":\"" + json(reason) + "\"}");
    }

    @Override
    @Transactional
    public void restoreByProject(Long projectId, String operator) {
        OrderEntity value = findByProjectId(projectId);
        if (value == null) return;
        if (!StringUtils.hasText(value.getPreviousStatus())) throw new BusinessException(ErrorCodeConstants.STATUS_TRANSITION_ILLEGAL, "订单缺少放弃前状态，不能自动恢复");
        value.setStatus(value.getPreviousStatus());
        value.setPreviousStatus(null); value.setCloseReason(null); value.setClosedAt(null); value.setClosedBy(null); value.setSourceAction(null);
        touch(value, operator); repository.updateById(value); log("ORDER_RESTORE_BY_PROJECT", value, "{}");
    }

    private void updateStatus(Long projectId, String status, String operator, String detail) {
        OrderEntity value = findByProjectId(projectId);
        if (value == null || "closed".equals(value.getStatus())) return;
        value.setStatus(status); touch(value, operator); repository.updateById(value); log("ORDER_STATUS_SYNC", value, detail == null ? "{}" : detail);
    }

    private void touch(OrderEntity value, String operator) { value.setUpdatedAt(LocalDateTime.now()); value.setUpdatedBy(StringUtils.hasText(operator) ? operator : "system"); }
    private void log(String action, OrderEntity value, String detail) { if (operationLogService != null) operationLogService.logSuccess(OperationLogCreateCommand.builder().action(action).businessType("ORDER").businessId(String.valueOf(value.getOrderId())).businessCode(value.getOrderCode()).businessName(value.getOrderTitle()).detailJson(detail).build()); }
    private String generateOrderCode() { return "ORD-" + LocalDate.now().format(DateTimeFormatter.BASIC_ISO_DATE) + "-" + String.format("%04d", ThreadLocalRandom.current().nextInt(10000)); }
    private OrderVO toVO(OrderEntity value) { return OrderVO.builder().orderId(value.getOrderId()).dingTalkApprovalNo(value.getDingTalkApprovalNo()).orderCode(value.getOrderCode()).phoneModel(value.getPhoneModel()).projectType(value.getProjectType()).orderType(value.getOrderType()).productName(value.getProductName()).status(value.getStatus()).projectId(value.getProjectId()).closeReason(value.getCloseReason()).createdAt(value.getCreatedAt()).build(); }
    private boolean contains(String value, String keyword) { return value != null && value.toLowerCase(Locale.ROOT).contains(keyword); }
    private String clean(String value) { return value == null ? "" : value.trim(); }
    private String json(String value) { return value == null ? "" : value.replace("\\", "\\\\").replace("\"", "\\\""); }
    private <T> T first(List<T> values) { return values == null || values.isEmpty() ? null : values.get(0); }
    private <T> List<T> safe(List<T> values) { return values == null ? List.of() : values; }
}

