package com.yuewei.plm.service.impl;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.yuewei.plm.common.config.JacksonConfig;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.common.security.CurrentUserContext;
import com.yuewei.plm.common.util.ProductCodeGenerator;
import com.yuewei.plm.controller.dto.ProductCreateDTO;
import com.yuewei.plm.controller.dto.ProductUpdateDTO;
import com.yuewei.plm.module.bom.entity.ProductProductionColorDecision;
import com.yuewei.plm.module.bom.repository.ProductProductionColorDecisionRepository;
import com.yuewei.plm.module.bom.service.BomInheritanceService;
import com.yuewei.plm.module.operationlog.constant.OperationActionConstants;
import com.yuewei.plm.module.operationlog.service.OperationLogCreateCommand;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.process.service.ProcessRouteInheritanceService;
import com.yuewei.plm.module.project.variant.entity.ProductVariantColor;
import com.yuewei.plm.module.project.variant.repository.ProductVariantColorRepository;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import com.yuewei.plm.service.ProductReleaseGateValidator;
import jakarta.servlet.http.HttpServletRequest;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;

class ProductServiceImplTest {

    @AfterEach
    void tearDown() {
        CurrentUserContext.clear();
    }

    @Test
    void freezeUsesCurrentUserAndWritesProductFreezeOperationLog() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProductCodeGenerator productCodeGenerator = mock(ProductCodeGenerator.class);
        OperationLogService operationLogService = mock(OperationLogService.class);
        ProductServiceImpl service = new ProductServiceImpl(
            productRepository,
            productCodeGenerator,
            operationLogService,
            new JacksonConfig().objectMapper(),
            mock(ProductReleaseGateValidator.class),
            mock(BomInheritanceService.class),
            mock(ProcessRouteInheritanceService.class),
            mock(ProductProductionColorDecisionRepository.class),
            mock(ProductVariantColorRepository.class)
        );
        Product product = new Product();
        product.setProductId(100L);
        product.setProductCode("PRD-CD30-IP18-BLK-A");
        product.setProductName("超队 3.0 iPhone18 黑色");
        product.setStatus("draft");
        product.setDeletedFlag(0);
        when(productRepository.selectById(100L)).thenReturn(product);
        CurrentUserContext.set(new CurrentUser(1L, "engineer01", "工程部用户一", true));
        HttpServletRequest request = mock(HttpServletRequest.class);
        ArgumentCaptor<Product> productCaptor = ArgumentCaptor.forClass(Product.class);
        ArgumentCaptor<OperationLogCreateCommand> logCaptor = ArgumentCaptor.forClass(OperationLogCreateCommand.class);

        service.freeze(100L, "M1操作人验证", request);

        verify(productRepository).updateById(productCaptor.capture());
        Product frozen = productCaptor.getValue();
        assertThat(frozen.getFrozenBy()).isEqualTo("工程部用户一");
        assertThat(frozen.getLockOperatorUserId()).isEqualTo(1L);
        assertThat(frozen.getLockOperatorUserName()).isEqualTo("工程部用户一");
        assertThat(frozen.getUpdatedBy()).isEqualTo("工程部用户一");

        verify(operationLogService).logSuccess(logCaptor.capture());
        OperationLogCreateCommand command = logCaptor.getValue();
        assertThat(command.getAction()).isEqualTo(OperationActionConstants.PRODUCT_FREEZE);
        assertThat(command.getBusinessType()).isEqualTo("PRODUCT");
        assertThat(command.getBusinessId()).isEqualTo("100");
        assertThat(command.getBusinessCode()).isEqualTo("PRD-CD30-IP18-BLK-A");
        assertThat(command.getBusinessName()).isEqualTo("超队 3.0 iPhone18 黑色");
        assertThat(command.getDetailJson()).contains("M1操作人验证");
        assertThat(command.getRequest()).isSameAs(request);
    }

    @Test
    void getByIdMapsCurrentStepNo() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProductCodeGenerator productCodeGenerator = mock(ProductCodeGenerator.class);
        OperationLogService operationLogService = mock(OperationLogService.class);
        ProductServiceImpl service = new ProductServiceImpl(
            productRepository,
            productCodeGenerator,
            operationLogService,
            new JacksonConfig().objectMapper(),
            mock(ProductReleaseGateValidator.class),
            mock(BomInheritanceService.class),
            mock(ProcessRouteInheritanceService.class),
            mock(ProductProductionColorDecisionRepository.class),
            mock(ProductVariantColorRepository.class)
        );
        Product product = new Product();
        product.setProductId(101L);
        product.setProductCode("PRD-CD30-0002");
        product.setProductName("超队 3.0");
        product.setProductType("product_line");
        product.setStatus("developing");
        product.setCurrentStepNo(3);
        product.setDeletedFlag(0);
        when(productRepository.selectById(101L)).thenReturn(product);

        var vo = service.getById(101L);

        assertThat(vo.getCurrentStepNo()).isEqualTo(3);
    }

    @Test
    void updateBasicInfoAllowsReleasedProductWithoutChangingVersionFields() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProductServiceImpl service = new ProductServiceImpl(
            productRepository,
            mock(ProductCodeGenerator.class),
            mock(OperationLogService.class),
            new JacksonConfig().objectMapper(),
            mock(ProductReleaseGateValidator.class),
            mock(BomInheritanceService.class),
            mock(ProcessRouteInheritanceService.class),
            mock(ProductProductionColorDecisionRepository.class),
            mock(ProductVariantColorRepository.class)
        );
        Product product = new Product();
        product.setProductId(102L);
        product.setProductCode("PRD-CD30-0003");
        product.setProductName("旧名称");
        product.setProductType("product_line");
        product.setVersionNo("A");
        product.setStatus("released");
        product.setLockStatus("frozen");
        product.setDeletedFlag(0);
        when(productRepository.selectById(102L)).thenReturn(product);
        ProductUpdateDTO dto = new ProductUpdateDTO();
        dto.setUpdatedBy("pm01");
        dto.setProductName("发布后基础信息名称");
        dto.setExpectedDeliveryDate(LocalDate.of(2026, 8, 20));

        var result = service.updateBasicInfo(102L, dto);

        verify(productRepository).updateById(product);
        assertThat(result.getProductName()).isEqualTo("发布后基础信息名称");
        assertThat(result.getStatus()).isEqualTo("released");
        assertThat(result.getVersionNo()).isEqualTo("A");
        assertThat(result.getExpectedDeliveryDate()).isEqualTo(LocalDate.of(2026, 8, 20));
    }

    @Test
    void creatingModelVariantInheritsConfirmedProductionColorsAndIgnoresFrontendColor() {
        ProductRepository repository = mock(ProductRepository.class);
        BomInheritanceService inheritance = mock(BomInheritanceService.class);
        ProductProductionColorDecisionRepository colorRepository = mock(ProductProductionColorDecisionRepository.class);
        ProductVariantColorRepository variantColorRepository = mock(ProductVariantColorRepository.class);
        ProductCodeGenerator generator = mock(ProductCodeGenerator.class);
        ProcessRouteInheritanceService processInheritance = mock(ProcessRouteInheritanceService.class);
        when(generator.generate("亮甲")).thenReturn("PRD-LJ-IP18");
        Product parent = new Product();
        parent.setProductId(5L);
        parent.setProductType("product_line");
        parent.setSeriesName("亮甲 3.0");
        parent.setStatus("released");
        parent.setDeletedFlag(0);
        when(repository.selectById(5L)).thenReturn(parent);
        when(colorRepository.selectList(Mockito.<Wrapper<ProductProductionColorDecision>>any())).thenReturn(List.of(
            color(10L, "01", "黑色"),
            color(11L, "02", "透明色")
        ));
        org.mockito.Mockito.doAnswer(invocation -> {
            Product created = invocation.getArgument(0);
            created.setProductId(20L);
            return 1;
        }).when(repository).insert(org.mockito.ArgumentMatchers.any(Product.class));
        when(processInheritance.inheritLatestReleasedFormalBomRoutesByColors(Mockito.eq(5L), Mockito.any(Product.class),
            Mockito.eq(List.of("黑色", "透明色")), Mockito.eq("engineer"))).thenReturn(Map.of(27L, 200L));
        ProductServiceImpl service = new ProductServiceImpl(repository, generator, mock(OperationLogService.class),
            new JacksonConfig().objectMapper(), mock(ProductReleaseGateValidator.class), inheritance,
            processInheritance, colorRepository, variantColorRepository);
        ProductCreateDTO dto = new ProductCreateDTO();
        dto.setParentProductId(5L); dto.setProductName("亮甲"); dto.setProductType("model_variant");
        dto.setModel("iPhone 18"); dto.setColor("前端手填颜色"); dto.setVersionNo("V1"); dto.setCreatedBy("engineer");

        service.create(dto);

        ArgumentCaptor<Product> productCaptor = ArgumentCaptor.forClass(Product.class);
        verify(repository).insert(productCaptor.capture());
        assertThat(productCaptor.getValue().getSeriesName()).isEqualTo("亮甲 3.0");
        assertThat(productCaptor.getValue().getColor()).isNull();

        ArgumentCaptor<ProductVariantColor> colorCaptor = ArgumentCaptor.forClass(ProductVariantColor.class);
        verify(variantColorRepository, Mockito.times(2)).insert(colorCaptor.capture());
        assertThat(colorCaptor.getAllValues()).extracting(ProductVariantColor::getColorName)
            .containsExactly("黑色", "透明色");
        assertThat(colorCaptor.getAllValues()).allMatch(value ->
            value.getProjectProductId().equals(20L)
                && value.getSourceProductId().equals(5L)
                && Integer.valueOf(1).equals(value.getDefaultSelectedFlag())
                && Integer.valueOf(1).equals(value.getSelectedFlag())
                && "active".equals(value.getSnapshotStatus())
        );

        verify(processInheritance).inheritLatestReleasedFormalBomRoutesByColors(Mockito.eq(5L), Mockito.any(Product.class),
            Mockito.eq(List.of("黑色", "透明色")), Mockito.eq("engineer"));
        verify(inheritance).inheritLatestReleasedByColors(5L, 20L, List.of("黑色", "透明色"), Map.of(27L, 200L));
    }

    @Test
    void creatingProductLineUsesProductLineBusinessCodeWhenSpecificCodeExists() {
        ProductRepository repository = mock(ProductRepository.class);
        ProductCodeGenerator generator = mock(ProductCodeGenerator.class);
        when(generator.generate("超队 4.0")).thenReturn("PRD-SUPER-0001");
        ProductServiceImpl service = new ProductServiceImpl(repository, generator, mock(OperationLogService.class),
            new JacksonConfig().objectMapper(), mock(ProductReleaseGateValidator.class), mock(BomInheritanceService.class),
            mock(ProcessRouteInheritanceService.class), mock(ProductProductionColorDecisionRepository.class),
            mock(ProductVariantColorRepository.class));
        ProductCreateDTO dto = new ProductCreateDTO();
        dto.setProductName("超队 4.0");
        dto.setProductType("product_line");
        dto.setProductSpecificCode("HA");
        dto.setSeriesName("超队");
        dto.setVersionNo("A");
        dto.setCreatedBy("engineer");

        service.create(dto);

        ArgumentCaptor<Product> productCaptor = ArgumentCaptor.forClass(Product.class);
        verify(repository).insert(productCaptor.capture());
        assertThat(productCaptor.getValue().getProductCode()).isEqualTo("NHA4030");
        assertThat(productCaptor.getValue().getProductSpecificCode()).isEqualTo("HA");
        assertThat(productCaptor.getValue().getFinishedProductCode()).isNull();
    }

    @Test
    void creatingModelVariantRejectsWhenParentHasNoConfirmedColors() {
        ProductRepository repository = mock(ProductRepository.class);
        ProductProductionColorDecisionRepository colorRepository = mock(ProductProductionColorDecisionRepository.class);
        ProductVariantColorRepository variantColorRepository = mock(ProductVariantColorRepository.class);
        Product parent = new Product();
        parent.setProductId(5L);
        parent.setProductType("product_line");
        parent.setStatus("released");
        parent.setDeletedFlag(0);
        when(repository.selectById(5L)).thenReturn(parent);
        when(colorRepository.selectList(Mockito.<Wrapper<ProductProductionColorDecision>>any())).thenReturn(List.of());
        BomInheritanceService inheritance = mock(BomInheritanceService.class);
        ProductServiceImpl service = new ProductServiceImpl(repository, mock(ProductCodeGenerator.class), mock(OperationLogService.class),
            new JacksonConfig().objectMapper(), mock(ProductReleaseGateValidator.class), inheritance,
            mock(ProcessRouteInheritanceService.class), colorRepository, variantColorRepository);
        ProductCreateDTO dto = new ProductCreateDTO();
        dto.setParentProductId(5L); dto.setProductName("亮甲"); dto.setProductType("model_variant");
        dto.setModel("iPhone 18"); dto.setVersionNo("V1"); dto.setCreatedBy("engineer");

        assertThatThrownBy(() -> service.create(dto))
            .isInstanceOf(BusinessException.class)
            .hasMessageContaining("尚未敲定正式投产颜色");

        verify(repository, never()).insert(Mockito.any(Product.class));
        verify(inheritance, never()).inheritLatestReleasedByColors(Mockito.anyLong(), Mockito.anyLong(), Mockito.anyList(), Mockito.anyMap());
    }

    private ProductProductionColorDecision color(Long id, String code, String name) {
        ProductProductionColorDecision value = new ProductProductionColorDecision();
        value.setProductProductionColorDecisionId(id);
        value.setProductId(5L);
        value.setCodeItemId(id);
        value.setColorCode(code);
        value.setColorName(name);
        value.setDecisionBatchNo("B1");
        value.setSelectedFlag(1);
        value.setStatus("confirmed");
        value.setDeletedFlag(0);
        return value;
    }
}
