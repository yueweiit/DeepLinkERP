package com.yuewei.plm.module.bom.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.util.ProductBusinessCodeGenerator;
import com.yuewei.plm.module.bom.dto.ProductionColorConfirmDTO;
import com.yuewei.plm.module.bom.dto.ProductionOperationConfirmDTO;
import com.yuewei.plm.module.bom.dto.ProductionRouteConfirmDTO;
import com.yuewei.plm.module.bom.entity.ProductBomRouteFormalSelection;
import com.yuewei.plm.module.bom.entity.ProductBom;
import com.yuewei.plm.module.bom.entity.ProductBomCostSnapshot;
import com.yuewei.plm.module.bom.entity.ProductBomRoute;
import com.yuewei.plm.module.bom.entity.ProductBomRouteColor;
import com.yuewei.plm.module.bom.entity.ProcessProductionOperationSelection;
import com.yuewei.plm.module.bom.entity.ProductProductionColorDecision;
import com.yuewei.plm.module.bom.repository.ProductBomRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteColorRepository;
import com.yuewei.plm.module.bom.repository.ProductBomCostSnapshotRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteFormalSelectionRepository;
import com.yuewei.plm.module.bom.repository.ProcessProductionOperationSelectionRepository;
import com.yuewei.plm.module.bom.repository.ProductProductionColorDecisionRepository;
import com.yuewei.plm.module.process.entity.ProcessEntity;
import com.yuewei.plm.module.process.repository.ProcessRepository;
import com.yuewei.plm.module.code.entity.CodeItem;
import com.yuewei.plm.module.code.service.CodeItemService;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import java.util.List;
import java.util.ArrayList;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

class ProductionConfirmationServiceTest {
    private ProductRepository productRepository;
    private ProductBomRepository bomRepository;
    private ProductBomRouteRepository routeRepository;
    private ProcessRepository processRepository;
    private ProductBomRouteColorRepository routeColorRepository;
    private ProductBomCostSnapshotRepository costRepository;
    private ProductBomRouteFormalSelectionRepository formalSelectionRepository;
    private ProcessProductionOperationSelectionRepository operationRepository;
    private ProductProductionColorDecisionRepository colorRepository;
    private CodeItemService codeItemService;
    private ProductionConfirmationService service;

    @BeforeEach
    void setUp() {
        productRepository = mock(ProductRepository.class);
        bomRepository = mock(ProductBomRepository.class);
        routeRepository = mock(ProductBomRouteRepository.class);
        processRepository = mock(ProcessRepository.class);
        routeColorRepository = mock(ProductBomRouteColorRepository.class);
        costRepository = mock(ProductBomCostSnapshotRepository.class);
        formalSelectionRepository = mock(ProductBomRouteFormalSelectionRepository.class);
        operationRepository = mock(ProcessProductionOperationSelectionRepository.class);
        colorRepository = mock(ProductProductionColorDecisionRepository.class);
        codeItemService = mock(CodeItemService.class);
        service = new ProductionConfirmationService(productRepository, bomRepository, routeRepository,
            processRepository, routeColorRepository, costRepository, formalSelectionRepository,
            operationRepository, colorRepository, codeItemService, new ProductBusinessCodeGenerator());
    }

    @Test
    void confirmRoutesInvalidatesPreviousFormalBomForSameProcess() {
        Product project = product(10L, "product_line", 10);
        ProductBom newBom = bom(400L, 10L, "released");
        ProductBomRoute newRoute = route(401L, 10L, 501L);
        newRoute.setProductBomId(400L);
        ProcessEntity selectedOperation = operation(601L, 501L);
        ProductBomRouteColor routeColor = routeColor(2L, "02", "Negro");
        CodeItem colorCode = colorCode(2L, "02", "Negro");
        ProductBomCostSnapshot cost = new ProductBomCostSnapshot();
        ProductBomRouteFormalSelection previous = new ProductBomRouteFormalSelection();
        previous.setProductBomRouteFormalSelectionId(1L);
        previous.setProductId(10L);
        previous.setProductBomId(300L);
        previous.setProductBomRouteId(301L);
        previous.setProcessId(501L);
        previous.setStatus("active");
        previous.setDeletedFlag(0);
        when(productRepository.selectById(10L)).thenReturn(project);
        when(bomRepository.selectById(400L)).thenReturn(newBom);
        when(routeRepository.selectById(401L)).thenReturn(newRoute);
        when(processRepository.selectById(501L)).thenReturn(operation(501L, null));
        when(processRepository.selectById(601L)).thenReturn(selectedOperation);
        when(routeColorRepository.selectList(any(Wrapper.class))).thenReturn(List.of(routeColor));
        when(codeItemService.requireEnabledColor(2L, "02")).thenReturn(colorCode);
        when(costRepository.selectList(any(Wrapper.class))).thenReturn(List.of(cost));
        when(formalSelectionRepository.selectList(any(Wrapper.class))).thenReturn(List.of(previous), List.of());

        ProductionRouteConfirmDTO.RouteSelection routeSelection = new ProductionRouteConfirmDTO.RouteSelection();
        routeSelection.setProcessId(501L);
        routeSelection.setProductBomId(400L);
        routeSelection.setProductBomRouteId(401L);
        routeSelection.setOperationProcessIds(List.of(601L));
        routeSelection.setApplicableColors(List.of(applicableColor(2L, "02", "Negro")));
        ProductionRouteConfirmDTO dto = new ProductionRouteConfirmDTO();
        dto.setRoutes(List.of(routeSelection));
        dto.setRemark("切换为新版 BOM");

        service.confirmRoutes(10L, dto);

        ArgumentCaptor<ProductBomRouteFormalSelection> updateCaptor = ArgumentCaptor.forClass(ProductBomRouteFormalSelection.class);
        verify(formalSelectionRepository).updateById(updateCaptor.capture());
        assertThat(updateCaptor.getValue().getStatus()).isEqualTo("invalidated");
        assertThat(updateCaptor.getValue().getInvalidatedReason()).contains("切换为新版 BOM");
        ArgumentCaptor<ProductBomRouteFormalSelection> insertCaptor = ArgumentCaptor.forClass(ProductBomRouteFormalSelection.class);
        verify(formalSelectionRepository).insert(insertCaptor.capture());
        assertThat(insertCaptor.getValue().getProductBomId()).isEqualTo(400L);
        assertThat(insertCaptor.getValue().getProductBomRouteId()).isEqualTo(401L);
        assertThat(insertCaptor.getValue().getProcessId()).isEqualTo(501L);
        verify(operationRepository).insert(any(ProcessProductionOperationSelection.class));
        ArgumentCaptor<ProductProductionColorDecision> colorCaptor = ArgumentCaptor.forClass(ProductProductionColorDecision.class);
        verify(colorRepository).insert(colorCaptor.capture());
        assertThat(colorCaptor.getValue().getCodeItemId()).isEqualTo(2L);
        assertThat(colorCaptor.getValue().getColorName()).isEqualTo("Negro");
        assertThat(colorCaptor.getValue().getProductBomRouteId()).isEqualTo(401L);
    }

    @Test
    void confirmRoutesKeepsMultipleSelectedBomsActiveForSameProcess() {
        Product project = product(10L, "product_line", 10);
        ProductBom firstBom = bom(400L, 10L, "released");
        ProductBom secondBom = bom(410L, 10L, "released");
        ProductBomRoute firstRoute = route(401L, 10L, 501L);
        firstRoute.setProductBomId(400L);
        ProductBomRoute secondRoute = route(411L, 10L, 501L);
        secondRoute.setProductBomId(410L);
        ProductBomRouteFormalSelection previous = new ProductBomRouteFormalSelection();
        previous.setProductBomRouteFormalSelectionId(1L);
        previous.setProductId(10L);
        previous.setProductBomId(300L);
        previous.setProductBomRouteId(301L);
        previous.setProcessId(501L);
        previous.setStatus("active");
        previous.setDeletedFlag(0);
        when(productRepository.selectById(10L)).thenReturn(project);
        when(bomRepository.selectById(400L)).thenReturn(firstBom);
        when(bomRepository.selectById(410L)).thenReturn(secondBom);
        when(routeRepository.selectById(401L)).thenReturn(firstRoute);
        when(routeRepository.selectById(411L)).thenReturn(secondRoute);
        when(processRepository.selectById(501L)).thenReturn(operation(501L, null));
        when(processRepository.selectById(601L)).thenReturn(operation(601L, 501L));
        when(routeColorRepository.selectList(any(Wrapper.class)))
            .thenReturn(List.of(routeColor(2L, "02", "Negro")));
        when(codeItemService.requireEnabledColor(2L, "02"))
            .thenReturn(colorCode(2L, "02", "Negro"));
        when(costRepository.selectList(any(Wrapper.class))).thenReturn(List.of(new ProductBomCostSnapshot()));
        when(formalSelectionRepository.selectList(any(Wrapper.class))).thenReturn(List.of(previous), List.of());

        ProductionRouteConfirmDTO.RouteSelection first = new ProductionRouteConfirmDTO.RouteSelection();
        first.setProcessId(501L);
        first.setProductBomId(400L);
        first.setProductBomRouteId(401L);
        first.setOperationProcessIds(List.of(601L));
        first.setApplicableColors(List.of(applicableColor(2L, "02", "Negro")));
        ProductionRouteConfirmDTO.RouteSelection second = new ProductionRouteConfirmDTO.RouteSelection();
        second.setProcessId(501L);
        second.setProductBomId(410L);
        second.setProductBomRouteId(411L);
        second.setOperationProcessIds(List.of(601L));
        second.setApplicableColors(List.of(applicableColor(2L, "02", "Negro")));
        ProductionRouteConfirmDTO dto = new ProductionRouteConfirmDTO();
        dto.setRoutes(List.of(first, second));

        service.confirmRoutes(10L, dto);

        verify(formalSelectionRepository, times(1)).updateById(previous);
        ArgumentCaptor<ProductBomRouteFormalSelection> inserts =
            ArgumentCaptor.forClass(ProductBomRouteFormalSelection.class);
        verify(formalSelectionRepository, times(2)).insert(inserts.capture());
        assertThat(inserts.getAllValues())
            .extracting(ProductBomRouteFormalSelection::getProductBomRouteId)
            .containsExactly(401L, 411L);
        assertThat(inserts.getAllValues())
            .allMatch(selection -> "active".equals(selection.getStatus()))
            .allMatch(selection -> selection.getProcessId().equals(501L));
        verify(operationRepository, times(2)).insert(any(ProcessProductionOperationSelection.class));
        verify(colorRepository, times(2)).insert(any(ProductProductionColorDecision.class));
    }

    @Test
    void confirmRoutesRejectsOperationsWithoutFormalBomSelection() {
        Product project = product(10L, "product_line", 10);
        when(productRepository.selectById(10L)).thenReturn(project);
        ProductionRouteConfirmDTO.RouteSelection routeSelection = new ProductionRouteConfirmDTO.RouteSelection();
        routeSelection.setProcessId(501L);
        routeSelection.setProductBomId(400L);
        routeSelection.setProductBomRouteId(401L);
        routeSelection.setOperationProcessIds(List.of());
        ProductionRouteConfirmDTO dto = new ProductionRouteConfirmDTO();
        dto.setRoutes(List.of(routeSelection));

        assertThatThrownBy(() -> service.confirmRoutes(10L, dto))
            .isInstanceOf(BusinessException.class)
            .hasMessageContaining("请至少选择一道投产工序");
        verify(formalSelectionRepository, never()).insert(any(ProductBomRouteFormalSelection.class));
        verify(operationRepository, never()).insert(any(ProcessProductionOperationSelection.class));
    }

    @Test
    void confirmRoutesRejectsMissingApplicableColors() {
        Product project = product(10L, "product_line", 10);
        ProductBom newBom = bom(400L, 10L, "released");
        ProductBomRoute newRoute = route(401L, 10L, 501L);
        newRoute.setProductBomId(400L);
        ProcessEntity selectedOperation = operation(601L, 501L);
        ProductBomCostSnapshot cost = new ProductBomCostSnapshot();
        when(productRepository.selectById(10L)).thenReturn(project);
        when(bomRepository.selectById(400L)).thenReturn(newBom);
        when(routeRepository.selectById(401L)).thenReturn(newRoute);
        when(processRepository.selectById(601L)).thenReturn(selectedOperation);
        when(costRepository.selectList(any(Wrapper.class))).thenReturn(List.of(cost));
        when(routeColorRepository.selectList(any(Wrapper.class))).thenReturn(List.of());

        ProductionRouteConfirmDTO.RouteSelection routeSelection = new ProductionRouteConfirmDTO.RouteSelection();
        routeSelection.setProcessId(501L);
        routeSelection.setProductBomId(400L);
        routeSelection.setProductBomRouteId(401L);
        routeSelection.setOperationProcessIds(List.of(601L));
        ProductionRouteConfirmDTO dto = new ProductionRouteConfirmDTO();
        dto.setRoutes(List.of(routeSelection));

        assertThatThrownBy(() -> service.confirmRoutes(10L, dto))
            .isInstanceOf(BusinessException.class)
            .hasMessageContaining("请至少选择一个适用颜色");
        verify(formalSelectionRepository, never()).insert(any(ProductBomRouteFormalSelection.class));
        verify(colorRepository, never()).insert(any(ProductProductionColorDecision.class));
    }

    @Test
    void confirmOperationsRejectsOperationOutsideSelectedRoute() {
        Product project = product(10L, "product_line", 10);
        ProductBomRoute route = route(100L, 10L, 200L);
        route.setProductBomId(400L);
        ProcessEntity foreignOperation = operation(301L, 999L);
        when(productRepository.selectById(10L)).thenReturn(project);
        when(bomRepository.selectById(400L)).thenReturn(bom(400L, 10L, "released"));
        when(routeRepository.selectById(100L)).thenReturn(route);
        when(processRepository.selectById(301L)).thenReturn(foreignOperation);

        ProductionOperationConfirmDTO dto = new ProductionOperationConfirmDTO();
        dto.setProductBomRouteId(100L);
        dto.setOperationProcessIds(List.of(301L));

        assertThatThrownBy(() -> service.confirmOperations(10L, dto))
            .isInstanceOf(BusinessException.class)
            .hasMessageContaining("不属于当前工艺路线");
        verify(operationRepository, never()).insert(any(ProcessProductionOperationSelection.class));
    }

    @Test
    void confirmColorsCreatesSkuOnceForRepeatedRequest() {
        Product project = product(20L, "model_variant", 16);
        project.setParentProductId(5L);
        project.setModel("iPhone 18");
        project.setProductSpecificCode("CD");
        project.setPhoneModelCode("1800");
        ProductBom bom = bom(400L, 20L, "released");
        ProductBomRoute route = route(401L, 20L, 501L);
        route.setProductBomId(400L);
        when(productRepository.selectById(20L)).thenReturn(project);
        when(bomRepository.selectById(400L)).thenReturn(bom);
        when(routeRepository.selectById(401L)).thenReturn(route);
        ProductBomRouteColor routeColor = new ProductBomRouteColor();
        routeColor.setCodeItemId(2L);
        routeColor.setColorCode("02");
        routeColor.setColorName("Negro");
        ProductBomCostSnapshot cost = new ProductBomCostSnapshot();
        ProductBomRouteFormalSelection formal = new ProductBomRouteFormalSelection();
        formal.setProductId(20L);
        formal.setProductBomId(400L);
        formal.setProductBomRouteId(401L);
        formal.setProcessId(501L);
        formal.setStatus("active");
        formal.setDeletedFlag(0);
        ProcessProductionOperationSelection selection = new ProcessProductionOperationSelection();
        selection.setOperationProcessId(601L);
        ProcessEntity routeProcess = operation(501L, null);
        routeProcess.setVersionNo("V1");
        ProcessEntity selectedOperation = operation(601L, 501L);
        when(routeColorRepository.selectList(any(Wrapper.class))).thenReturn(List.of(routeColor));
        when(costRepository.selectList(any(Wrapper.class))).thenReturn(List.of(cost));
        when(formalSelectionRepository.selectList(any(Wrapper.class))).thenReturn(List.of(formal));
        when(operationRepository.selectList(any(Wrapper.class))).thenReturn(List.of(selection));
        when(processRepository.selectById(501L)).thenReturn(routeProcess);
        when(processRepository.selectById(601L)).thenReturn(selectedOperation);
        List<ProductProductionColorDecision> persistedColors = new ArrayList<>();
        when(colorRepository.selectList(any(Wrapper.class))).thenAnswer(invocation -> persistedColors);
        when(colorRepository.insert(any(ProductProductionColorDecision.class))).thenAnswer(invocation -> {
            persistedColors.add(invocation.getArgument(0));
            return 1;
        });
        Product existingSku = product(900L, "sku", 1);
        existingSku.setParentProductId(20L);
        existingSku.setColor("Negro");
        existingSku.setColorCode("02");
        when(productRepository.selectList(any(Wrapper.class))).thenReturn(List.of(), List.of(existingSku));
        CodeItem codeItem = new CodeItem();
        codeItem.setCodeItemId(2L); codeItem.setCodeType("color"); codeItem.setCodeValue("02");
        codeItem.setCodeName("Negro"); codeItem.setStatus("enabled"); codeItem.setDeletedFlag(0);
        when(codeItemService.requireEnabledColor(2L, "02")).thenReturn(codeItem);

        ProductionColorConfirmDTO.ColorSelection color = new ProductionColorConfirmDTO.ColorSelection();
        color.setCodeItemId(2L);
        color.setColorCode("02");
        color.setColorName("Negro");
        color.setProductBomId(400L);
        color.setProductBomRouteId(401L);
        ProductionColorConfirmDTO dto = new ProductionColorConfirmDTO();
        dto.setColors(List.of(color));

        var first = service.confirmColors(20L, dto);
        var second = service.confirmColors(20L, dto);

        assertThat(first.getSelectedColorCount()).isEqualTo(1);
        assertThat(second.getSelectedColorCount()).isEqualTo(1);
        verify(productRepository).insert(any(Product.class));
        ArgumentCaptor<Product> skuCaptor = ArgumentCaptor.forClass(Product.class);
        verify(productRepository).insert(skuCaptor.capture());
        assertThat(skuCaptor.getValue().getColor()).isEqualTo("Negro");
        assertThat(skuCaptor.getValue().getColorCode()).isEqualTo("02");
        assertThat(skuCaptor.getValue().getPhoneModelCode()).isEqualTo("1800");
        assertThat(project.getColor()).isEqualTo("Negro");
        assertThat(project.getColorCode()).isEqualTo("02");
    }

    @Test
    void syncModelVariantMovesProjectOwnedFinishedProductCodeToSku() {
        Product project = product(20L, "model_variant", 16);
        project.setModel("S269");
        project.setProductSpecificCode("CD");
        project.setPhoneModelCode("1800");
        project.setFinishedProductCode("NCD4030180002");
        ProductProductionColorDecision decision = new ProductProductionColorDecision();
        decision.setProductId(20L);
        decision.setCodeItemId(2L);
        decision.setColorCode("02");
        decision.setColorName("Negro");
        decision.setSelectedFlag(1);
        decision.setStatus("confirmed");
        decision.setDeletedFlag(0);
        when(colorRepository.selectList(any(Wrapper.class))).thenReturn(List.of(decision));
        when(productRepository.selectList(any(Wrapper.class))).thenReturn(List.of(), List.of(project));

        int created = service.syncModelVariantConfirmedColorsAndSkus(project);

        assertThat(created).isEqualTo(1);
        ArgumentCaptor<Product> skuCaptor = ArgumentCaptor.forClass(Product.class);
        verify(productRepository).insert(skuCaptor.capture());
        assertThat(skuCaptor.getValue().getProductCode()).isEqualTo("PRD-20-02");
        assertThat(skuCaptor.getValue().getFinishedProductCode()).isEqualTo("NCD4030180002");
        assertThat(project.getFinishedProductCode()).isNull();
        assertThat(project.getColor()).isEqualTo("Negro");
        assertThat(project.getColorCode()).isEqualTo("02");
    }

    @Test
    void syncModelVariantUsesParentProductLineOperationCodeForSkuFinishedProductCode() {
        Product project = product(20L, "model_variant", 16);
        project.setParentProductId(10L);
        project.setModel("S269");
        project.setProductSpecificCode("FA");
        project.setPhoneModelCode("1291");
        Product parent = product(10L, "product_line", 16);
        parent.setProductCode("NFA4020");
        ProductProductionColorDecision decision = new ProductProductionColorDecision();
        decision.setProductId(20L);
        decision.setCodeItemId(2L);
        decision.setColorCode("02");
        decision.setColorName("Negro");
        decision.setSelectedFlag(1);
        decision.setStatus("confirmed");
        decision.setDeletedFlag(0);
        when(colorRepository.selectList(any(Wrapper.class))).thenReturn(List.of(decision));
        when(productRepository.selectList(any(Wrapper.class))).thenReturn(List.of(), List.of());
        when(productRepository.selectById(10L)).thenReturn(parent);

        int created = service.syncModelVariantConfirmedColorsAndSkus(project);

        assertThat(created).isEqualTo(1);
        ArgumentCaptor<Product> skuCaptor = ArgumentCaptor.forClass(Product.class);
        verify(productRepository).insert(skuCaptor.capture());
        assertThat(skuCaptor.getValue().getFinishedProductCode()).isEqualTo("NFA4020129102");
    }

    @Test
    void confirmColorsRejectsDisabledCodeItemBeforeCreatingSku() {
        Product project = product(20L, "model_variant", 16);
        when(productRepository.selectById(20L)).thenReturn(project);
        when(codeItemService.requireEnabledColor(2L, "02"))
            .thenThrow(new BusinessException(40001, "颜色编码已停用"));
        ProductionColorConfirmDTO.ColorSelection color = new ProductionColorConfirmDTO.ColorSelection();
        color.setCodeItemId(2L); color.setColorCode("02"); color.setColorName("Negro");
        color.setProductBomId(400L); color.setProductBomRouteId(401L);
        ProductionColorConfirmDTO dto = new ProductionColorConfirmDTO(); dto.setColors(List.of(color));

        assertThatThrownBy(() -> service.confirmColors(20L, dto)).hasMessageContaining("颜色编码已停用");
        verify(productRepository, never()).insert(any(Product.class));
    }

    @Test
    void confirmRoutesRejectsDraftBom() {
        Product project = product(10L, "product_line", 10);
        when(productRepository.selectById(10L)).thenReturn(project);
        when(bomRepository.selectById(400L)).thenReturn(bom(400L, 10L, "draft"));

        ProductionRouteConfirmDTO.RouteSelection routeSelection = new ProductionRouteConfirmDTO.RouteSelection();
        routeSelection.setProcessId(501L);
        routeSelection.setProductBomId(400L);
        routeSelection.setProductBomRouteId(401L);
        routeSelection.setOperationProcessIds(List.of(601L));
        routeSelection.setApplicableColors(List.of(applicableColor(2L, "02", "Negro")));
        ProductionRouteConfirmDTO dto = new ProductionRouteConfirmDTO();
        dto.setRoutes(List.of(routeSelection));

        assertThatThrownBy(() -> service.confirmRoutes(10L, dto))
            .isInstanceOf(BusinessException.class)
            .hasMessageContaining("使用 BOM 必须是当前项目已定版 BOM");
        verify(formalSelectionRepository, never()).insert(any(ProductBomRouteFormalSelection.class));
    }

    @Test
    void requireOperationsConfirmedAcceptsLegacySelectionWithoutRouteVersion() {
        Product project = product(10L, "product_line", 10);
        ProductBomRoute route = route(401L, 10L, 501L);
        ProductBomRouteFormalSelection formal = new ProductBomRouteFormalSelection();
        formal.setProductId(10L);
        formal.setProductBomRouteId(401L);
        formal.setProcessId(501L);
        formal.setStatus("active");
        formal.setDeletedFlag(0);
        ProcessProductionOperationSelection selection = new ProcessProductionOperationSelection();
        selection.setProductId(10L);
        selection.setProductBomRouteId(401L);
        selection.setOperationProcessId(601L);
        selection.setStatus("confirmed");
        selection.setDeletedFlag(0);
        ProcessEntity routeProcess = operation(501L, null);
        routeProcess.setVersionNo("V2");
        when(productRepository.selectById(10L)).thenReturn(project);
        when(formalSelectionRepository.selectList(any(Wrapper.class))).thenReturn(List.of(formal));
        when(routeRepository.selectById(401L)).thenReturn(route);
        when(processRepository.selectById(501L)).thenReturn(routeProcess);
        when(operationRepository.selectList(any(Wrapper.class))).thenReturn(List.of(selection));
        when(processRepository.selectById(601L)).thenReturn(operation(601L, 501L));

        service.requireOperationsConfirmed(10L);
    }

    @Test
    void requireOperationsConfirmedSkipsStaleFormalSelectionWhenValidRouteExists() {
        Product project = product(10L, "product_line", 10);
        ProductBomRoute staleRoute = route(301L, 10L, 501L);
        staleRoute.setStatus("inactive");
        ProductBomRoute validRoute = route(401L, 10L, 501L);
        ProductBomRouteFormalSelection staleFormal = new ProductBomRouteFormalSelection();
        staleFormal.setProductId(10L);
        staleFormal.setProductBomRouteFormalSelectionId(3010L);
        staleFormal.setProductBomRouteId(301L);
        staleFormal.setProcessId(501L);
        staleFormal.setStatus("active");
        staleFormal.setDeletedFlag(0);
        ProductBomRouteFormalSelection validFormal = new ProductBomRouteFormalSelection();
        validFormal.setProductId(10L);
        validFormal.setProductBomRouteFormalSelectionId(4010L);
        validFormal.setProductBomRouteId(401L);
        validFormal.setProcessId(501L);
        validFormal.setStatus("active");
        validFormal.setDeletedFlag(0);
        ProcessProductionOperationSelection selection = new ProcessProductionOperationSelection();
        selection.setProductId(10L);
        selection.setProductBomRouteId(401L);
        selection.setOperationProcessId(601L);
        selection.setStatus("confirmed");
        selection.setDeletedFlag(0);
        ProcessEntity routeProcess = operation(501L, null);
        routeProcess.setVersionNo("V2");
        when(productRepository.selectById(10L)).thenReturn(project);
        when(formalSelectionRepository.selectList(any(Wrapper.class))).thenReturn(List.of(staleFormal, validFormal));
        when(routeRepository.selectById(301L)).thenReturn(staleRoute);
        when(routeRepository.selectById(401L)).thenReturn(validRoute);
        when(processRepository.selectById(501L)).thenReturn(routeProcess);
        when(operationRepository.selectList(any(Wrapper.class))).thenReturn(List.of(selection));
        when(processRepository.selectById(601L)).thenReturn(operation(601L, 501L));

        service.requireOperationsConfirmed(10L);

        verify(formalSelectionRepository).updateById(staleFormal);
        assertThat(staleFormal.getStatus()).isEqualTo("invalidated");
        assertThat(staleFormal.getInvalidatedReason()).contains("BOM 路线已失效");
    }

    @Test
    void requireOperationsConfirmedAcceptsLegacyRouteWithoutProductId() {
        Product project = product(10L, "product_line", 10);
        ProductBomRoute route = route(401L, null, 501L);
        ProductBomRouteFormalSelection formal = new ProductBomRouteFormalSelection();
        formal.setProductId(10L);
        formal.setProductBomRouteId(401L);
        formal.setProcessId(501L);
        formal.setStatus("active");
        formal.setDeletedFlag(0);
        ProcessProductionOperationSelection selection = new ProcessProductionOperationSelection();
        selection.setProductId(10L);
        selection.setProductBomRouteId(401L);
        selection.setOperationProcessId(601L);
        selection.setStatus("confirmed");
        selection.setDeletedFlag(0);
        ProcessEntity routeProcess = operation(501L, null);
        routeProcess.setVersionNo("V2");
        when(productRepository.selectById(10L)).thenReturn(project);
        when(formalSelectionRepository.selectList(any(Wrapper.class))).thenReturn(List.of(formal));
        when(routeRepository.selectById(401L)).thenReturn(route);
        when(processRepository.selectById(501L)).thenReturn(routeProcess);
        when(operationRepository.selectList(any(Wrapper.class))).thenReturn(List.of(selection));
        when(processRepository.selectById(601L)).thenReturn(operation(601L, 501L));

        service.requireOperationsConfirmed(10L);
    }

    @Test
    void getFallsBackColorDisplayNameFromCodeWhenNameIsBlank() {
        Product project = product(10L, "product_line", 10);
        ProductBomRoute route = route(401L, 10L, 501L);
        route.setRouteName("染色工艺路线");
        ProductBomRouteFormalSelection formal = new ProductBomRouteFormalSelection();
        formal.setProductId(10L);
        formal.setProductBomId(400L);
        formal.setProductBomRouteId(401L);
        formal.setProcessId(501L);
        formal.setBomVersionNo("V1");
        formal.setStatus("active");
        formal.setDeletedFlag(0);
        ProductProductionColorDecision color = new ProductProductionColorDecision();
        color.setProductId(10L);
        color.setCodeItemId(2L);
        color.setColorCode("02");
        color.setColorName(" ");
        color.setProductBomId(400L);
        color.setProductBomRouteId(401L);
        color.setStatus("confirmed");
        color.setSelectedFlag(1);
        color.setDeletedFlag(0);
        when(productRepository.selectById(10L)).thenReturn(project);
        when(operationRepository.selectList(any(Wrapper.class))).thenReturn(List.of());
        when(colorRepository.selectList(any(Wrapper.class))).thenReturn(List.of(color));
        when(formalSelectionRepository.selectList(any(Wrapper.class))).thenReturn(List.of(formal));
        when(routeRepository.selectById(401L)).thenReturn(route);

        var result = service.get(10L);

        assertThat(result.getColors()).containsExactly("02");
        assertThat(result.getRouteSelections()).hasSize(1);
        assertThat(result.getRouteSelections().get(0).getApplicableColors()).hasSize(1);
        assertThat(result.getRouteSelections().get(0).getApplicableColors().get(0).getColorCode()).isEqualTo("02");
        assertThat(result.getRouteSelections().get(0).getApplicableColors().get(0).getColorName()).isEqualTo("02");
    }

    private Product product(Long id, String type, int step) {
        Product value = new Product();
        value.setProductId(id);
        value.setProductCode("PRD-" + id);
        value.setProductName("亮甲");
        value.setProductType(type);
        value.setCurrentStepNo(step);
        value.setDeletedFlag(0);
        return value;
    }

    private ProductBom bom(Long id, Long productId, String status) {
        ProductBom value = new ProductBom();
        value.setProductBomId(id);
        value.setProductId(productId);
        value.setStatus(status);
        value.setVersionNo("V1");
        value.setDeletedFlag(0);
        return value;
    }

    private ProductBomRoute route(Long id, Long productId, Long processId) {
        ProductBomRoute value = new ProductBomRoute();
        value.setProductBomRouteId(id);
        value.setProductId(productId);
        value.setProcessId(processId);
        value.setRouteCode("R1");
        value.setStatus("active");
        value.setDeletedFlag(0);
        return value;
    }

    private ProcessEntity operation(Long id, Long parentId) {
        ProcessEntity value = new ProcessEntity();
        value.setProcessId(id);
        value.setParentProcessId(parentId);
        value.setStatus("confirmed");
        value.setDeletedFlag(0);
        return value;
    }

    private ProductBomRouteColor routeColor(Long codeItemId, String colorCode, String colorName) {
        ProductBomRouteColor value = new ProductBomRouteColor();
        value.setCodeItemId(codeItemId);
        value.setColorCode(colorCode);
        value.setColorName(colorName);
        value.setStatus("active");
        value.setDeletedFlag(0);
        return value;
    }

    private ProductionRouteConfirmDTO.ApplicableColor applicableColor(Long codeItemId, String colorCode, String colorName) {
        ProductionRouteConfirmDTO.ApplicableColor value = new ProductionRouteConfirmDTO.ApplicableColor();
        value.setCodeItemId(codeItemId);
        value.setColorCode(colorCode);
        value.setColorName(colorName);
        return value;
    }

    private CodeItem colorCode(Long codeItemId, String colorCode, String colorName) {
        CodeItem value = new CodeItem();
        value.setCodeItemId(codeItemId);
        value.setCodeType("color");
        value.setCodeValue(colorCode);
        value.setCodeName(colorName);
        value.setStatus("enabled");
        value.setDeletedFlag(0);
        return value;
    }
}
