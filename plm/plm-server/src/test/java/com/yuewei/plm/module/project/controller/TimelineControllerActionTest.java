package com.yuewei.plm.module.project.controller;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.yuewei.plm.module.project.dto.TimelineActionDTO;
import com.yuewei.plm.module.project.service.TimelineActionService;
import com.yuewei.plm.module.project.service.TimelineService;
import com.yuewei.plm.module.project.vo.TimelineActionResultVO;
import jakarta.servlet.http.HttpServletRequest;
import org.junit.jupiter.api.Test;

class TimelineControllerActionTest {

    @Test
    void confirmEndpointDelegatesToTimelineActionService() {
        TimelineService timelineService = mock(TimelineService.class);
        TimelineActionService timelineActionService = mock(TimelineActionService.class);
        TimelineController controller = new TimelineController(timelineService, timelineActionService);
        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getHeader("X-Request-Id")).thenReturn("m3-confirm-001");
        TimelineActionDTO dto = TimelineActionDTO.builder().remark("checked").build();
        TimelineActionResultVO result = result("confirm");
        when(timelineActionService.confirm(1L, "PRODUCT_LINE_INIT_CONFIRM", dto, request)).thenReturn(result);

        var response = controller.confirm(1L, "PRODUCT_LINE_INIT_CONFIRM", dto, request);

        assertThat(response.getCode()).isZero();
        assertThat(response.getData()).isSameAs(result);
        assertThat(response.getRequestId()).isEqualTo("m3-confirm-001");
        verify(timelineActionService).confirm(1L, "PRODUCT_LINE_INIT_CONFIRM", dto, request);
    }

    @Test
    void advanceEndpointDelegatesToTimelineActionService() {
        TimelineService timelineService = mock(TimelineService.class);
        TimelineActionService timelineActionService = mock(TimelineActionService.class);
        TimelineController controller = new TimelineController(timelineService, timelineActionService);
        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getHeader("X-Request-Id")).thenReturn("m3-advance-001");
        TimelineActionDTO dto = TimelineActionDTO.builder().remark("go").build();
        TimelineActionResultVO result = result("advance");
        when(timelineActionService.advance(2L, "PRODUCT_LINE_DESIGN_CONFIRM", dto, request)).thenReturn(result);

        var response = controller.advance(2L, "PRODUCT_LINE_DESIGN_CONFIRM", dto, request);

        assertThat(response.getCode()).isZero();
        assertThat(response.getData()).isSameAs(result);
        assertThat(response.getRequestId()).isEqualTo("m3-advance-001");
        verify(timelineActionService).advance(2L, "PRODUCT_LINE_DESIGN_CONFIRM", dto, request);
    }

    @Test
    void returnEndpointDelegatesToTimelineActionService() {
        TimelineService timelineService = mock(TimelineService.class);
        TimelineActionService timelineActionService = mock(TimelineActionService.class);
        TimelineController controller = new TimelineController(timelineService, timelineActionService);
        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getHeader("X-Request-Id")).thenReturn("m3-return-001");
        TimelineActionDTO dto = TimelineActionDTO.builder().reason("missing docs").returnToPrevious(true).build();
        TimelineActionResultVO result = result("return");
        when(timelineActionService.returnNode(3L, "PRODUCT_LINE_MOLD_TRIAL", dto, request)).thenReturn(result);

        var response = controller.returnNode(3L, "PRODUCT_LINE_MOLD_TRIAL", dto, request);

        assertThat(response.getCode()).isZero();
        assertThat(response.getData()).isSameAs(result);
        assertThat(response.getRequestId()).isEqualTo("m3-return-001");
        verify(timelineActionService).returnNode(3L, "PRODUCT_LINE_MOLD_TRIAL", dto, request);
    }

    private TimelineActionResultVO result(String action) {
        return TimelineActionResultVO.builder()
            .projectId(1L)
            .productId(1L)
            .action(action)
            .nodeKey("PRODUCT_LINE_INIT_CONFIRM")
            .beforeStepNo(1)
            .currentStepNo(1)
            .currentNodeKey("PRODUCT_LINE_INIT_CONFIRM")
            .currentNodeName("init")
            .currentConfirmed(true)
            .productStatus("draft")
            .logId(10L)
            .build();
    }
}
