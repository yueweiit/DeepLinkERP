package com.yuewei.plm.service.impl;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.yuewei.plm.common.config.JacksonConfig;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.common.security.CurrentUserContext;
import com.yuewei.plm.common.util.ProductCodeGenerator;
import com.yuewei.plm.controller.dto.ProductLifecycleActionDTO;
import com.yuewei.plm.module.operationlog.constant.OperationActionConstants;
import com.yuewei.plm.module.operationlog.service.OperationLogCreateCommand;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import com.yuewei.plm.service.ProductReleaseGateValidator;
import com.yuewei.plm.service.vo.ProductReleaseGateCheckVO;
import com.yuewei.plm.service.vo.ProductReleaseGateMissingItemVO;
import jakarta.servlet.http.HttpServletRequest;
import java.util.List;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

class ProductServiceLifecycleTest {

    @AfterEach
    void tearDown() {
        CurrentUserContext.clear();
    }

    @Test
    void publishRequiresRiskConfirmationWhenMaterialsAreMissing() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProductReleaseGateValidator releaseGateValidator = mock(ProductReleaseGateValidator.class);
        ProductServiceImpl service = service(productRepository, mock(OperationLogService.class), releaseGateValidator);
        Product product = product("developing");
        ProductReleaseGateCheckVO gate = ProductReleaseGateCheckVO.builder()
            .projectId(10L)
            .productId(10L)
            .passed(true)
            .blocking(false)
            .confirmRequired(true)
            .missingItems(List.of(ProductReleaseGateMissingItemVO.builder()
                .code("BOM_NOT_FROZEN")
                .message("缺少已冻结或已发布 BOM")
                .severity("warning")
                .build()))
            .build();
        when(productRepository.selectById(10L)).thenReturn(product);
        when(releaseGateValidator.check(product)).thenReturn(gate);
        CurrentUserContext.set(new CurrentUser(1L, "engineer01", "工程一", true));

        assertThatThrownBy(() -> service.publish(10L, action("发布"), mock(HttpServletRequest.class)))
            .isInstanceOf(BusinessException.class)
            .satisfies(ex -> {
                BusinessException businessException = (BusinessException) ex;
                assertThat(businessException.getCode()).isEqualTo(ErrorCodeConstants.RELEASE_RISK_CONFIRM_REQUIRED);
                assertThat(businessException.getData()).isSameAs(gate);
            });
    }

    @Test
    void publishAllowsMissingMaterialsAfterRiskConfirmationAndLogsRiskDetails() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProductReleaseGateValidator releaseGateValidator = mock(ProductReleaseGateValidator.class);
        OperationLogService operationLogService = mock(OperationLogService.class);
        ProductServiceImpl service = service(productRepository, operationLogService, releaseGateValidator);
        Product product = product("developing");
        ProductReleaseGateCheckVO gate = ProductReleaseGateCheckVO.builder()
            .projectId(10L)
            .productId(10L)
            .passed(true)
            .blocking(false)
            .confirmRequired(true)
            .missingItems(List.of(ProductReleaseGateMissingItemVO.builder()
                .code("TESTING_FILE_MISSING")
                .message("缺少测试资料")
                .severity("warning")
                .build()))
            .build();
        when(productRepository.selectById(10L)).thenReturn(product);
        when(releaseGateValidator.check(product)).thenReturn(gate);
        CurrentUserContext.set(new CurrentUser(1L, "engineer01", "工程一", true));
        ArgumentCaptor<OperationLogCreateCommand> logCaptor = ArgumentCaptor.forClass(OperationLogCreateCommand.class);

        var result = service.publish(10L, action("确认风险发布", true), mock(HttpServletRequest.class));

        assertThat(result.getStatus()).isEqualTo("released");
        verify(operationLogService).logSuccess(logCaptor.capture());
        assertThat(logCaptor.getValue().getDetailJson())
            .contains("\"riskConfirmed\":true")
            .contains("TESTING_FILE_MISSING")
            .contains("缺少测试资料");
    }

    @Test
    void publishUpdatesProductToReleasedAndWritesOperationLogWhenGatePasses() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProductReleaseGateValidator releaseGateValidator = mock(ProductReleaseGateValidator.class);
        OperationLogService operationLogService = mock(OperationLogService.class);
        ProductServiceImpl service = service(productRepository, operationLogService, releaseGateValidator);
        Product product = product("developing");
        when(productRepository.selectById(10L)).thenReturn(product);
        when(releaseGateValidator.check(product)).thenReturn(ProductReleaseGateCheckVO.builder()
            .projectId(10L)
            .productId(10L)
            .passed(true)
            .missingItems(List.of())
            .build());
        CurrentUserContext.set(new CurrentUser(1L, "manager01", "管理层一", true));
        ArgumentCaptor<Product> productCaptor = ArgumentCaptor.forClass(Product.class);
        ArgumentCaptor<OperationLogCreateCommand> logCaptor = ArgumentCaptor.forClass(OperationLogCreateCommand.class);

        var result = service.publish(10L, action("资料齐备"), mock(HttpServletRequest.class));

        verify(productRepository).updateById(productCaptor.capture());
        assertThat(productCaptor.getValue().getStatus()).isEqualTo("released");
        assertThat(productCaptor.getValue().getReleasedBy()).isEqualTo("管理层一");
        assertThat(result.getStatus()).isEqualTo("released");
        verify(operationLogService).logSuccess(logCaptor.capture());
        assertThat(logCaptor.getValue().getAction()).isEqualTo(OperationActionConstants.PRODUCT_PUBLISH);
        assertThat(logCaptor.getValue().getDetailJson()).contains("资料齐备");
    }

    @Test
    void archiveMovesReleasedProductToArchivedAndWritesOperationLog() {
        ProductRepository productRepository = mock(ProductRepository.class);
        OperationLogService operationLogService = mock(OperationLogService.class);
        ProductServiceImpl service = service(productRepository, operationLogService, mock(ProductReleaseGateValidator.class));
        Product product = product("released");
        when(productRepository.selectById(10L)).thenReturn(product);
        CurrentUserContext.set(new CurrentUser(2L, "pm01", "项目经理一", true));
        ArgumentCaptor<Product> productCaptor = ArgumentCaptor.forClass(Product.class);
        ArgumentCaptor<OperationLogCreateCommand> logCaptor = ArgumentCaptor.forClass(OperationLogCreateCommand.class);

        var result = service.archive(10L, action("历史归档"), mock(HttpServletRequest.class));

        verify(productRepository).updateById(productCaptor.capture());
        assertThat(productCaptor.getValue().getStatus()).isEqualTo("archived");
        assertThat(productCaptor.getValue().getArchivedBy()).isEqualTo("项目经理一");
        assertThat(result.getStatus()).isEqualTo("archived");
        verify(operationLogService).logSuccess(logCaptor.capture());
        assertThat(logCaptor.getValue().getAction()).isEqualTo(OperationActionConstants.PRODUCT_ARCHIVE);
    }

    @Test
    void abandonArchivesUnreleasedProductWithAbandonedLockStatus() {
        ProductRepository productRepository = mock(ProductRepository.class);
        OperationLogService operationLogService = mock(OperationLogService.class);
        ProductServiceImpl service = service(productRepository, operationLogService, mock(ProductReleaseGateValidator.class));
        Product product = product("developing");
        when(productRepository.selectById(10L)).thenReturn(product);
        CurrentUserContext.set(new CurrentUser(3L, "pm02", "项目经理二", true));
        ArgumentCaptor<Product> productCaptor = ArgumentCaptor.forClass(Product.class);
        ArgumentCaptor<OperationLogCreateCommand> logCaptor = ArgumentCaptor.forClass(OperationLogCreateCommand.class);

        var result = service.abandon(10L, action("业务取消"), mock(HttpServletRequest.class));

        verify(productRepository).updateById(productCaptor.capture());
        assertThat(productCaptor.getValue().getStatus()).isEqualTo("archived");
        assertThat(productCaptor.getValue().getLockStatus()).isEqualTo("abandoned");
        assertThat(productCaptor.getValue().getAbandonedBy()).isEqualTo("项目经理二");
        assertThat(result.getStatus()).isEqualTo("archived");
        assertThat(result.getLockStatus()).isEqualTo("abandoned");
        verify(operationLogService).logSuccess(logCaptor.capture());
        assertThat(logCaptor.getValue().getAction()).isEqualTo(OperationActionConstants.PRODUCT_ABANDON);
    }

    @Test
    void legacyPublishUsesOperatorWhenCurrentUserContextIsMissing() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProductReleaseGateValidator releaseGateValidator = mock(ProductReleaseGateValidator.class);
        OperationLogService operationLogService = mock(OperationLogService.class);
        ProductServiceImpl service = service(productRepository, operationLogService, releaseGateValidator);
        Product product = product("developing");
        when(productRepository.selectById(10L)).thenReturn(product);
        when(releaseGateValidator.check(product)).thenReturn(ProductReleaseGateCheckVO.builder()
            .projectId(10L)
            .productId(10L)
            .passed(true)
            .missingItems(List.of())
            .build());

        service.publish(10L, "legacy-operator");

        assertThat(product.getStatus()).isEqualTo("released");
        assertThat(product.getReleasedBy()).isEqualTo("legacy-operator");
        verify(operationLogService).logSuccess(any(OperationLogCreateCommand.class));
    }

    @Test
    void archivedProductCannotBePublishedAgain() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProductReleaseGateValidator releaseGateValidator = mock(ProductReleaseGateValidator.class);
        ProductServiceImpl service = service(productRepository, mock(OperationLogService.class), releaseGateValidator);
        Product product = product("archived");
        when(productRepository.selectById(10L)).thenReturn(product);
        when(releaseGateValidator.check(product)).thenReturn(ProductReleaseGateCheckVO.builder()
            .projectId(10L)
            .productId(10L)
            .passed(false)
            .missingItems(List.of(ProductReleaseGateMissingItemVO.builder()
                .code("PRODUCT_ARCHIVED")
                .message("产品已归档，不能发布")
                .build()))
            .build());
        CurrentUserContext.set(new CurrentUser(1L, "manager01", "管理层一", true));

        assertThatThrownBy(() -> service.publish(10L, action("归档后发布"), mock(HttpServletRequest.class)))
            .isInstanceOf(BusinessException.class)
            .extracting("code")
            .isEqualTo(ErrorCodeConstants.RELEASE_GATE_NOT_PASSED);
    }

    @Test
    void releasedProductCannotBeAbandoned() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProductServiceImpl service = service(productRepository, mock(OperationLogService.class), mock(ProductReleaseGateValidator.class));
        when(productRepository.selectById(10L)).thenReturn(product("released"));
        CurrentUserContext.set(new CurrentUser(1L, "manager01", "管理层一", true));

        assertThatThrownBy(() -> service.abandon(10L, action("不能废弃"), mock(HttpServletRequest.class)))
            .isInstanceOf(BusinessException.class)
            .extracting("code")
            .isEqualTo(ErrorCodeConstants.STATUS_TRANSITION_ILLEGAL);
    }

    private ProductServiceImpl service(
        ProductRepository productRepository,
        OperationLogService operationLogService,
        ProductReleaseGateValidator releaseGateValidator
    ) {
        return new ProductServiceImpl(
            productRepository,
            mock(ProductCodeGenerator.class),
            operationLogService,
            new JacksonConfig().objectMapper(),
            releaseGateValidator,
            mock(com.yuewei.plm.module.bom.service.BomInheritanceService.class),
            mock(com.yuewei.plm.module.process.service.ProcessRouteInheritanceService.class),
            mock(com.yuewei.plm.module.bom.repository.ProductProductionColorDecisionRepository.class),
            mock(com.yuewei.plm.module.project.variant.repository.ProductVariantColorRepository.class)
        );
    }

    private Product product(String status) {
        Product product = new Product();
        product.setProductId(10L);
        product.setProductCode("PRD-CD30-0001");
        product.setProductName("超队3.0");
        product.setProductType("product_line");
        product.setVersionNo("A");
        product.setStatus(status);
        product.setDeletedFlag(0);
        return product;
    }

    private ProductLifecycleActionDTO action(String reason) {
        return action(reason, false);
    }

    private ProductLifecycleActionDTO action(String reason, boolean riskConfirmed) {
        ProductLifecycleActionDTO dto = new ProductLifecycleActionDTO();
        dto.setReason(reason);
        dto.setRiskConfirmed(riskConfirmed);
        return dto;
    }
}
