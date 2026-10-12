package com.yuewei.plm.module.project.controller;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.yuewei.plm.controller.dto.ProductLifecycleActionDTO;
import com.yuewei.plm.service.ProductService;
import com.yuewei.plm.service.vo.ProductReleaseGateCheckVO;
import com.yuewei.plm.service.vo.ProductVO;
import jakarta.servlet.http.HttpServletRequest;
import java.util.List;
import org.junit.jupiter.api.Test;

class ProjectLifecycleControllerTest {

    @Test
    void releaseGateEndpointDelegatesToProductService() {
        ProductService productService = mock(ProductService.class);
        ProjectLifecycleController controller = new ProjectLifecycleController(productService);
        HttpServletRequest request = request("m5-gate");
        ProductReleaseGateCheckVO gate = ProductReleaseGateCheckVO.builder()
            .projectId(10L)
            .productId(10L)
            .passed(false)
            .missingItems(List.of())
            .build();
        when(productService.checkReleaseGate(10L)).thenReturn(gate);

        var response = controller.checkReleaseGate(10L, request);

        assertThat(response.getCode()).isZero();
        assertThat(response.getRequestId()).isEqualTo("m5-gate");
        assertThat(response.getData()).isSameAs(gate);
        verify(productService).checkReleaseGate(10L);
    }

    @Test
    void publishEndpointDelegatesToProductService() {
        ProductService productService = mock(ProductService.class);
        ProjectLifecycleController controller = new ProjectLifecycleController(productService);
        HttpServletRequest request = request("m5-publish");
        ProductLifecycleActionDTO dto = new ProductLifecycleActionDTO();
        dto.setReason("资料齐备");
        ProductVO product = ProductVO.builder().productId(10L).status("released").build();
        when(productService.publish(10L, dto, request)).thenReturn(product);

        var response = controller.publish(10L, dto, request);

        assertThat(response.getCode()).isZero();
        assertThat(response.getData().getStatus()).isEqualTo("released");
        verify(productService).publish(10L, dto, request);
    }

    @Test
    void archiveAndAbandonEndpointsDelegateToProductService() {
        ProductService productService = mock(ProductService.class);
        ProjectLifecycleController controller = new ProjectLifecycleController(productService);
        HttpServletRequest request = request("m5-life");
        ProductLifecycleActionDTO dto = new ProductLifecycleActionDTO();
        dto.setReason("收口");
        ProductVO archived = ProductVO.builder().productId(10L).status("archived").build();
        when(productService.archive(10L, dto, request)).thenReturn(archived);
        when(productService.abandon(11L, dto, request)).thenReturn(archived);

        assertThat(controller.archive(10L, dto, request).getData().getStatus()).isEqualTo("archived");
        assertThat(controller.abandon(11L, dto, request).getData().getStatus()).isEqualTo("archived");
        verify(productService).archive(10L, dto, request);
        verify(productService).abandon(11L, dto, request);
    }

    private HttpServletRequest request(String requestId) {
        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getHeader("X-Request-Id")).thenReturn(requestId);
        return request;
    }
}
