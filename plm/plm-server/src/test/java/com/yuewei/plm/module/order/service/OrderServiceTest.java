package com.yuewei.plm.module.order.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.order.dto.OrderQueryDTO;
import com.yuewei.plm.module.order.entity.OrderEntity;
import com.yuewei.plm.module.order.repository.OrderRepository;
import com.yuewei.plm.module.order.service.impl.OrderServiceImpl;
import java.time.LocalDateTime;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;

class OrderServiceTest {

    @Test
    void listKeepsDingTalkCodeOrderCodeAndPhoneModel() {
        OrderRepository repository = mock(OrderRepository.class);
        OrderServiceImpl service = new OrderServiceImpl(repository, mock(OperationLogService.class));
        when(repository.selectList(Mockito.<Wrapper<OrderEntity>>any())).thenReturn(List.of(
            order(1L, "DT-1001", "ORD-20260720-0001", "iPhone 18", "model_variant", "confirmed"),
            order(2L, "DT-1002", "ORD-20260720-0002", null, "product_line", "completed")
        ));

        var page = service.page(query("100"));

        assertThat(page.getContent()).hasSize(2);
        assertThat(page.getContent().get(0).getDingTalkApprovalNo()).isEqualTo("DT-1001");
        assertThat(page.getContent().get(0).getOrderCode()).isEqualTo("ORD-20260720-0001");
        assertThat(page.getContent().get(0).getPhoneModel()).isEqualTo("iPhone 18");
        assertThat(page.getContent().get(1).getPhoneModel()).isNull();
    }

    @Test
    void projectAbandonClosesOrderAndPreservesPreviousStatus() {
        OrderRepository repository = mock(OrderRepository.class);
        OrderServiceImpl service = new OrderServiceImpl(repository, mock(OperationLogService.class));
        OrderEntity value = order(1L, "DT-1001", "ORD-20260720-0001", "iPhone 18", "model_variant", "in_production");
        when(repository.selectList(Mockito.<Wrapper<OrderEntity>>any())).thenReturn(List.of(value));

        service.closeByProject(9L, "停止开模", "engineer");

        ArgumentCaptor<OrderEntity> captor = ArgumentCaptor.forClass(OrderEntity.class);
        verify(repository).updateById(captor.capture());
        assertThat(captor.getValue().getStatus()).isEqualTo("closed");
        assertThat(captor.getValue().getPreviousStatus()).isEqualTo("in_production");
        assertThat(captor.getValue().getCloseReason()).isEqualTo("停止开模");
        assertThat(captor.getValue().getSourceAction()).isEqualTo("project_abandoned");
    }

    private OrderQueryDTO query(String keyword) {
        OrderQueryDTO query = new OrderQueryDTO();
        query.setPage(1L);
        query.setSize(20L);
        query.setKeyword(keyword);
        return query;
    }

    private OrderEntity order(Long id, String dingTalkNo, String orderCode, String model, String projectType, String status) {
        OrderEntity value = new OrderEntity();
        value.setOrderId(id);
        value.setProjectId(id + 8);
        value.setDingTalkApprovalNo(dingTalkNo);
        value.setOrderCode(orderCode);
        value.setPhoneModel(model);
        value.setProjectType(projectType);
        value.setOrderType("customer_requirement");
        value.setOrderTitle("需求 " + id);
        value.setProductName("超队 3.0");
        value.setStatus(status);
        value.setCreatedAt(LocalDateTime.now());
        value.setDeletedFlag(0);
        return value;
    }
}
