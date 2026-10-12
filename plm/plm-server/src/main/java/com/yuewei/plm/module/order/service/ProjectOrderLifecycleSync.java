package com.yuewei.plm.module.order.service;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class ProjectOrderLifecycleSync {
    private final OrderService orderService;

    public void inProduction(Long projectId, String operator) { orderService.markInProduction(projectId, operator); }
    public void completed(Long projectId, String operator) { orderService.completeByProject(projectId, operator); }
    public void abandoned(Long projectId, String reason, String operator) { orderService.closeByProject(projectId, reason, operator); }
    public void restored(Long projectId, String operator) { orderService.restoreByProject(projectId, operator); }
}
