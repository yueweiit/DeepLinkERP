package com.yuewei.plm.module.order.service;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

import org.junit.jupiter.api.Test;

class ProjectOrderLifecycleSyncTest {
    @Test
    void delegatesProjectLifecycleToOrderStateMachine() {
        OrderService orderService = mock(OrderService.class);
        ProjectOrderLifecycleSync service = new ProjectOrderLifecycleSync(orderService);

        service.inProduction(9L, "engineer");
        service.completed(9L, "engineer");
        service.abandoned(9L, "停止开模", "engineer");

        verify(orderService).markInProduction(9L, "engineer");
        verify(orderService).completeByProject(9L, "engineer");
        verify(orderService).closeByProject(9L, "停止开模", "engineer");
    }
}
