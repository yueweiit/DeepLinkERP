package com.yuewei.plm.module.bom.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.module.bom.dto.BomRouteSaveDTO;
import com.yuewei.plm.module.bom.dto.ProductBomItemDTO;
import com.yuewei.plm.module.bom.entity.ProductBom;
import com.yuewei.plm.module.bom.entity.ProductBomCostSnapshot;
import com.yuewei.plm.module.bom.entity.ProductBomItem;
import com.yuewei.plm.module.bom.entity.ProductBomRoute;
import com.yuewei.plm.module.bom.repository.ProductBomCostSnapshotRepository;
import com.yuewei.plm.module.bom.repository.ProductBomItemRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteColorRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteRepository;
import com.yuewei.plm.module.code.entity.CodeItem;
import com.yuewei.plm.module.code.service.CodeItemService;
import com.yuewei.plm.module.process.entity.ProcessEntity;
import com.yuewei.plm.module.process.repository.ProcessRepository;
import java.math.BigDecimal;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;

class ProductBomWorkflowServiceTest {
    private final com.yuewei.plm.module.pilot.PilotAccessService amountAccess=mock(com.yuewei.plm.module.pilot.PilotAccessService.class);

    @org.junit.jupiter.api.BeforeEach void realOperatorContext() {
        when(amountAccess.hasPermission("finance:write")).thenReturn(true);
        com.yuewei.plm.common.security.CurrentUserContext.set(new com.yuewei.plm.common.security.CurrentUser(1L,"test-engineer","测试工程师",true));
    }
    @org.junit.jupiter.api.AfterEach void clearOperatorContext() { com.yuewei.plm.common.security.CurrentUserContext.clear(); }

    @Test
    void saveRoutesRejectsMultipleRoutesForOneBom() {
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProductBomWorkflowService service = service(bomRepository);
        ProductBom bom = bom(10L, "draft", 0);
        when(bomRepository.selectById(10L)).thenReturn(bom);

        BomRouteSaveDTO dye = route(1L, "DYE", List.of("02"));
        BomRouteSaveDTO coating = route(2L, "COATING", List.of("08"));

        assertThatThrownBy(() -> service.saveRoutes(10L, List.of(dye, coating)))
            .isInstanceOf(BusinessException.class)
            .hasMessageContaining("同一套 BOM 的颜色副本必须绑定同一条工艺路线");
    }

    @Test
    void saveRoutesPersistsRouteSnapshotFromExistingProductProcess() {
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProductBomRouteRepository routeRepository = mock(ProductBomRouteRepository.class);
        ProductBomItemRepository itemRepository = mock(ProductBomItemRepository.class);
        ProductBomRouteColorRepository colorRepository = mock(ProductBomRouteColorRepository.class);
        CodeItemService codeItemService = mock(CodeItemService.class);
        ProcessRepository processRepository = processRepository(100L, 20L, "REAL-ROUTE", "真实工艺路线");
        ProductBom bom = bom(10L, "draft", 0);
        when(bomRepository.selectById(10L)).thenReturn(bom);
        when(routeRepository.selectList(Mockito.<Wrapper<ProductBomRoute>>any())).thenReturn(List.of());
        when(itemRepository.selectList(Mockito.<Wrapper<ProductBomItem>>any())).thenReturn(List.of());
        when(codeItemService.requireEnabledColor(null, "02")).thenReturn(color(2L, "02", "Negro"));
        BomRouteSaveDTO route = route(100L, "FAKE-CODE", List.of("02"));
        route.setRouteName("伪造路线名称");
        route.setItems(List.of(validItem()));
        ProductBomWorkflowService service = workflow(
            bomRepository, routeRepository, colorRepository, itemRepository, mock(ProductBomCostSnapshotRepository.class),
            new BomCostCalculator(),
            mock(BomTimelineGate.class), codeItemService, processRepository,
            mock(ProductBomService.class)
        );

        service.saveRoutes(10L, List.of(route));

        ArgumentCaptor<ProductBomRoute> captor = ArgumentCaptor.forClass(ProductBomRoute.class);
        verify(routeRepository).insert(captor.capture());
        assertThat(captor.getValue().getRouteCode()).isEqualTo("REAL-ROUTE");
        assertThat(captor.getValue().getRouteName()).isEqualTo("真实工艺路线");
    }

    @Test
    void saveRoutesCannotPublishEvenAnEditableLegacyFormalDraft() {
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProductBomRouteRepository routeRepository = mock(ProductBomRouteRepository.class);
        ProductBomItemRepository itemRepository = mock(ProductBomItemRepository.class);
        ProductBomRouteColorRepository colorRepository = mock(ProductBomRouteColorRepository.class);
        ProductBomService formalPublisher = mock(ProductBomService.class);
        CodeItemService codeItemService = mock(CodeItemService.class);
        ProductBom bom = bom(10L, "draft", 0);
        bom.setBomScope("formal");
        ProductBomRoute oldRoute = routeEntity(300L, 10L, 20L, 100L);
        when(bomRepository.selectById(10L)).thenReturn(bom);
        when(routeRepository.selectList(Mockito.<Wrapper<ProductBomRoute>>any())).thenReturn(List.of(oldRoute));
        when(colorRepository.selectList(Mockito.<Wrapper<com.yuewei.plm.module.bom.entity.ProductBomRouteColor>>any())).thenReturn(List.of());
        when(itemRepository.selectList(Mockito.<Wrapper<ProductBomItem>>any())).thenReturn(List.of());
        when(codeItemService.requireEnabledColor(null, "02")).thenReturn(color(2L, "02", "Negro"));
        Mockito.doAnswer(invocation -> {
            ProductBomRoute inserted = invocation.getArgument(0);
            inserted.setProductBomRouteId(701L);
            return 1;
        }).when(routeRepository).insert(any(ProductBomRoute.class));
        ProductBomWorkflowService service = workflow(
            bomRepository, routeRepository, colorRepository, itemRepository, mock(ProductBomCostSnapshotRepository.class),
            new BomCostCalculator(), mock(BomTimelineGate.class), codeItemService,
            processRepository(100L, 20L, "REAL-ROUTE", "真实工艺路线"),
            formalPublisher
        );

        service.saveRoutes(10L, List.of(route(100L, "REAL-ROUTE", List.of("02"))));

        assertThat(oldRoute.getStatus()).isEqualTo("inactive");
        assertThat(oldRoute.getDeletedFlag()).isEqualTo(1);
        assertThat(bom.getStatus()).isEqualTo("draft");assertThat(bom.getConfirmedAt()).isNull();assertThat(bom.getReleasedAt()).isNull();
        Mockito.verifyNoInteractions(formalPublisher);verify(bomRepository,Mockito.never()).updateById(bom);
    }

    @Test
    void saveRoutesRejectsRouteOutsideCurrentProduct() {
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProductBom bom = bom(10L, "draft", 0);
        when(bomRepository.selectById(10L)).thenReturn(bom);
        ProductBomWorkflowService service = workflow(
            bomRepository, mock(ProductBomRouteRepository.class), mock(ProductBomRouteColorRepository.class),
            mock(ProductBomItemRepository.class), mock(ProductBomCostSnapshotRepository.class),
            new BomCostCalculator(),
            mock(BomTimelineGate.class), mock(CodeItemService.class), processRepository(100L, 999L, "OTHER", "其他产品路线"),
            mock(ProductBomService.class)
        );

        assertThatThrownBy(() -> service.saveRoutes(10L, List.of(route(100L, "OTHER", List.of("02")))))
            .isInstanceOf(BusinessException.class)
            .hasMessageContaining("当前产品下已有");
    }

    @Test
    void reviewedPublishDoesNotRequireFreezeButStillRequiresCompleteRoutes() {
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProductBomWorkflowService service = service(bomRepository);
        when(bomRepository.selectById(10L)).thenReturn(bom(10L, "reviewing", 0));

        assertThatThrownBy(() -> service.publish(10L))
            .isInstanceOf(BusinessException.class)
            .hasMessageContaining("至少需要一条有效工艺路线");
    }

    @Test
    void confirmsTestBomAsSingleTotalCost() {
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProductBomItemRepository itemRepository = mock(ProductBomItemRepository.class);
        ProductBomWorkflowService service = workflow(
            bomRepository, mock(ProductBomRouteRepository.class), mock(ProductBomRouteColorRepository.class),
            itemRepository, mock(ProductBomCostSnapshotRepository.class),
            new BomCostCalculator(),
            mock(BomTimelineGate.class), mock(CodeItemService.class), mock(ProcessRepository.class),
            mock(ProductBomService.class)
        );
        ProductBom testBom = bom(30L, "draft", 0);
        testBom.setBomScope("test");
        testBom.setVersionNo("T1");
        ProductBomItem item = new ProductBomItem();
        item.setQuantity(new BigDecimal("2"));
        item.setUnitCostSnapshot(new BigDecimal("5"));
        item.setCurrencyCode("CNY");
        item.setLossRate(new BigDecimal("0.10"));
        when(bomRepository.selectOne(Mockito.<Wrapper<ProductBom>>any())).thenReturn(testBom);
        when(itemRepository.selectList(Mockito.<Wrapper<ProductBomItem>>any())).thenReturn(List.of(item));

        ProductBom confirmed = service.confirmTestBom(20L);

        assertThat(confirmed.getStatus()).isEqualTo("confirmed");
        assertThat(confirmed.getTestTotalCost()).isEqualByComparingTo("11");
        verify(bomRepository).updateById(testBom);
    }

    @Test
    void saveRoutesPersistsSupplierLineCostAndManualFlags() {
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProductBomRouteRepository routeRepository = mock(ProductBomRouteRepository.class);
        ProductBomRouteColorRepository colorRepository = mock(ProductBomRouteColorRepository.class);
        ProductBomItemRepository itemRepository = mock(ProductBomItemRepository.class);
        CodeItemService codeItemService = mock(CodeItemService.class);
        ProductBom bom = bom(10L, "draft", 0);
        bom.setCurrencyCode("CNY");
        when(bomRepository.selectById(10L)).thenReturn(bom);
        when(routeRepository.selectList(Mockito.<Wrapper<ProductBomRoute>>any())).thenReturn(List.of());
        when(itemRepository.selectList(Mockito.<Wrapper<ProductBomItem>>any())).thenReturn(List.of());
        when(codeItemService.requireEnabledColor(null, "02")).thenReturn(color(2L, "02", "Negro"));
        Mockito.doAnswer(invocation -> {
            ProductBomRoute inserted = invocation.getArgument(0);
            inserted.setProductBomRouteId(700L);
            return 1;
        }).when(routeRepository).insert(any(ProductBomRoute.class));
        ProductBomWorkflowService service = workflow(
            bomRepository, routeRepository, colorRepository, itemRepository, mock(ProductBomCostSnapshotRepository.class),
            new BomCostCalculator(),
            mock(BomTimelineGate.class), codeItemService,
            processRepository(100L, 20L, "DYE", "染色路线"),
            mock(ProductBomService.class)
        );
        ProductBomItemDTO item = validItem();
        item.setItemCode("MAT-001");
        item.setUnitCost(new BigDecimal("12.50"));
        item.setLineCost(new BigDecimal("25.00"));
        item.setSupplierCode("SUP-A");
        item.setSupplierName("东莞塑胶 A");
        item.setCurrencyCode("MXN");
        item.setMaterialSource("manual");
        item.setUnmatchedFlag(1);
        BomRouteSaveDTO route = route(100L, "DYE", List.of("02"));
        route.setItems(List.of(item));

        service.saveRoutes(10L, List.of(route));

        ArgumentCaptor<ProductBomItem> captor = ArgumentCaptor.forClass(ProductBomItem.class);
        verify(itemRepository).insert(captor.capture());
        ProductBomItem inserted = captor.getValue();
        assertThat(inserted.getProductBomRouteId()).isEqualTo(700L);
        assertThat(inserted.getSupplierCodeSnapshot()).isEqualTo("SUP-A");
        assertThat(inserted.getSupplierNameSnapshot()).isEqualTo("东莞塑胶 A");
        assertThat(inserted.getUnitCostSnapshot()).isEqualByComparingTo("12.50");
        assertThat(inserted.getLineCostSnapshot()).isEqualByComparingTo("25.00");
        assertThat(inserted.getCurrencyCode()).isEqualTo("MXN");
        assertThat(inserted.getMaterialSource()).isEqualTo("manual");
        assertThat(inserted.getUnmatchedFlag()).isEqualTo(1);
    }

    @Test
    void recalculateCostsPersistsCurrentCostSnapshotWithRouteCostInputs() {
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProductBomRouteRepository routeRepository = mock(ProductBomRouteRepository.class);
        ProductBomItemRepository itemRepository = mock(ProductBomItemRepository.class);
        ProductBomCostSnapshotRepository costRepository = mock(ProductBomCostSnapshotRepository.class);
        ProductBom bom = bom(10L, "draft", 0);
        bom.setCurrencyCode("CNY");
        ProductBomRoute route = new ProductBomRoute();
        route.setProductBomRouteId(700L);
        route.setProductBomId(10L);
        route.setProductId(20L);
        route.setProcessId(100L);
        route.setRouteCode("DYE");
        route.setRouteName("Dye route");
        route.setStatus("active");
        ProductBomItem item = new ProductBomItem();
        item.setQuantity(new BigDecimal("2"));
        item.setUnitCostSnapshot(new BigDecimal("12.50"));
        item.setCurrencyCode("CNY");
        item.setLossRate(new BigDecimal("0.10"));
        BomRouteSaveDTO input = route(100L, "DYE", List.of("02"));
        input.setProcessCost(new BigDecimal("3.00"));
        when(bomRepository.selectById(10L)).thenReturn(bom);
        when(routeRepository.selectList(Mockito.<Wrapper<ProductBomRoute>>any())).thenReturn(List.of(route));
        when(itemRepository.selectList(Mockito.<Wrapper<ProductBomItem>>any())).thenReturn(List.of(item));
        when(costRepository.selectList(Mockito.<Wrapper<ProductBomCostSnapshot>>any())).thenReturn(List.of());
        ProductBomWorkflowService service = workflow(
            bomRepository, routeRepository, mock(ProductBomRouteColorRepository.class), itemRepository, costRepository,
            new BomCostCalculator(),
            mock(BomTimelineGate.class), mock(CodeItemService.class), mock(ProcessRepository.class),
            mock(ProductBomService.class)
        );

        List<ProductBomCostSnapshot> snapshots = service.recalculateCosts(10L, List.of(input));

        assertThat(snapshots).hasSize(1);
        ArgumentCaptor<ProductBomCostSnapshot> captor = ArgumentCaptor.forClass(ProductBomCostSnapshot.class);
        verify(costRepository).insert(captor.capture());
        ProductBomCostSnapshot snapshot = captor.getValue();
        assertThat(snapshot.getProductBomId()).isEqualTo(10L);
        assertThat(snapshot.getProductBomRouteId()).isEqualTo(700L);
        assertThat(snapshot.getMaterialCost()).isEqualByComparingTo("25.00");
        assertThat(snapshot.getLossCost()).isEqualByComparingTo("2.500");
        assertThat(snapshot.getProcessCost()).isEqualByComparingTo("3.00");
        assertThat(snapshot.getTotalCost()).isEqualByComparingTo("30.500");
        assertThat(snapshot.getSourceSnapshotJson()).isEqualTo("{}");
        assertThat(snapshot.getStatus()).isEqualTo("current");
    }

    private ProductBomWorkflowService service(ProductBomRepository bomRepository) {
        return workflow(
            bomRepository,
            mock(ProductBomRouteRepository.class),
            mock(ProductBomRouteColorRepository.class),
            mock(ProductBomItemRepository.class),
            mock(ProductBomCostSnapshotRepository.class),
            new BomCostCalculator(),
            mock(BomTimelineGate.class),
            mock(CodeItemService.class),
            mock(ProcessRepository.class),
            mock(ProductBomService.class)
        );
    }

    @Test void reviewDoesNotPublishAndPublicationDelegatesToTheSingleFormalAction() {
        var boms=mock(ProductBomRepository.class);var routes=mock(ProductBomRouteRepository.class);var colors=mock(ProductBomRouteColorRepository.class);var items=mock(ProductBomItemRepository.class);var costs=mock(ProductBomCostSnapshotRepository.class);var formal=mock(ProductBomService.class);var gate=mock(BomTimelineGate.class);ProductBom b=bom(10L,"draft",0);b.setBomScope("candidate");
        when(boms.selectById(10L)).thenReturn(b);when(routes.selectList(Mockito.<Wrapper<ProductBomRoute>>any())).thenReturn(List.of(routeEntity(31L,10L,20L,41L)));when(colors.selectList(Mockito.any())).thenReturn(List.of(new com.yuewei.plm.module.bom.entity.ProductBomRouteColor()));when(items.selectList(Mockito.<Wrapper<ProductBomItem>>any())).thenReturn(List.of(new ProductBomItem()));when(costs.selectList(Mockito.any())).thenReturn(List.of(new ProductBomCostSnapshot()));
        ProductBomWorkflowService service=workflow(boms,routes,colors,items,costs,new BomCostCalculator(),gate,mock(CodeItemService.class),mock(ProcessRepository.class),formal);
        service.submitReview(10L);assertThat(b.getStatus()).isEqualTo("reviewing");Mockito.verifyNoInteractions(formal);
        Mockito.doAnswer(call->{b.setStatus("released");b.setBomScope("formal");return null;}).when(formal).confirmCurrentVersion(10L,null);assertThat(service.publish(10L)).isSameAs(b);verify(formal).confirmCurrentVersion(10L,null);verify(gate).requireFreezeOrPublishNode(20L);assertThat(b.getStatus()).isEqualTo("released");service.publish(10L);verify(formal,Mockito.times(1)).confirmCurrentVersion(10L,null);
    }

    private ProductBomWorkflowService workflow(ProductBomRepository boms,ProductBomRouteRepository routes,ProductBomRouteColorRepository colors,ProductBomItemRepository items,ProductBomCostSnapshotRepository costs,BomCostCalculator calculator,BomTimelineGate gate,CodeItemService codes,ProcessRepository processes,ProductBomService formal){return new ProductBomWorkflowService(boms,routes,colors,items,costs,calculator,gate,codes,processes,formal,amountAccess);}

    @Test void nonFinanceRouteAndVersionCopyUseStableSourceLineAndRetainOriginalCurrency() {
        when(amountAccess.hasPermission("finance:write")).thenReturn(false);var boms=mock(ProductBomRepository.class);var routes=mock(ProductBomRouteRepository.class);var items=mock(ProductBomItemRepository.class);var codes=mock(CodeItemService.class);
        ProductBom bom=bom(10L,"draft",0);var source=routeEntity(300L,9L,20L,100L);source.setDeletedFlag(1);var original=new ProductBomItem();original.setProductBomRouteId(300L);original.setLineNo(1);original.setQuantity(new BigDecimal("2"));original.setUnitCostSnapshot(new BigDecimal("5"));original.setLineCostSnapshot(new BigDecimal("10"));original.setCurrencyCode("USD");original.setDeletedFlag(1);
        when(boms.selectById(10L)).thenReturn(bom);when(routes.selectList(Mockito.any())).thenReturn(List.of(),List.of(source),List.of());when(items.selectList(Mockito.any())).thenReturn(List.of(original),List.of());when(codes.requireEnabledColor(null,"02")).thenReturn(color(2L,"02","Negro"));
        var dto=route(100L,"REAL",List.of("02"));dto.setSourceProductBomRouteId(300L);var line=validItem();line.setUnitCost(null);line.setLineCost(null);line.setCurrencyCode(null);line.setQuantity(new BigDecimal("3"));dto.setItems(List.of(line));
        var service=workflow(boms,routes,mock(ProductBomRouteColorRepository.class),items,mock(ProductBomCostSnapshotRepository.class),new BomCostCalculator(),mock(BomTimelineGate.class),codes,processRepository(100L,20L,"REAL","Real route"),mock(ProductBomService.class));service.saveRoutes(10L,List.of(dto));
        var captured=ArgumentCaptor.forClass(ProductBomItem.class);verify(items).insert(captured.capture());assertThat(captured.getValue().getUnitCostSnapshot()).isEqualByComparingTo("5");assertThat(captured.getValue().getLineCostSnapshot()).isEqualByComparingTo("15");assertThat(captured.getValue().getCurrencyCode()).isEqualTo("USD");
        // An inherited current route may reference a parent's route; only its own server line supplies money.
        var inherited=routeEntity(400L,10L,20L,100L);inherited.setSourceProductBomRouteId(300L);original.setProductBomRouteId(400L);original.setDeletedFlag(0);when(routes.selectList(Mockito.any())).thenReturn(List.of(inherited));when(items.selectList(Mockito.any())).thenReturn(List.of(original));dto.setProductBomRouteId(400L);service.saveRoutes(10L,List.of(dto));
        var copied=ArgumentCaptor.forClass(ProductBomItem.class);verify(items,Mockito.times(2)).insert(copied.capture());assertThat(copied.getAllValues().get(1).getUnitCostSnapshot()).isEqualByComparingTo("5");assertThat(copied.getAllValues().get(1).getCurrencyCode()).isEqualTo("USD");
    }

    @Test void nonFinanceReplacementWithoutStablePricedRouteIdIsRejectedBeforeArchiving() {
        when(amountAccess.hasPermission("finance:write")).thenReturn(false);var boms=mock(ProductBomRepository.class);var routes=mock(ProductBomRouteRepository.class);var items=mock(ProductBomItemRepository.class);var existing=routeEntity(300L,10L,20L,100L);var line=new ProductBomItem();line.setProductBomRouteId(300L);line.setLineNo(1);line.setUnitCostSnapshot(BigDecimal.TEN);when(boms.selectById(10L)).thenReturn(bom(10L,"draft",0));when(routes.selectList(Mockito.any())).thenReturn(List.of(existing));when(items.selectList(Mockito.any())).thenReturn(List.of(line));
        var dto=route(100L,"REAL",List.of("02"));dto.getItems().get(0).setUnitCost(null);var service=workflow(boms,routes,mock(ProductBomRouteColorRepository.class),items,mock(ProductBomCostSnapshotRepository.class),new BomCostCalculator(),mock(BomTimelineGate.class),mock(CodeItemService.class),mock(ProcessRepository.class),mock(ProductBomService.class));
        assertThatThrownBy(()->service.saveRoutes(10L,List.of(dto))).hasMessageContaining("稳定原路线 ID");verify(routes,Mockito.never()).updateById(any(ProductBomRoute.class));verify(items,Mockito.never()).insert(any(ProductBomItem.class));
        line.setProductBomRouteId(null);line.setProductBomId(10L);when(routes.selectList(Mockito.any())).thenReturn(List.of());assertThatThrownBy(()->service.saveRoutes(10L,List.of(dto))).hasMessageContaining("稳定原路线 ID");verify(items,Mockito.never()).insert(any(ProductBomItem.class));
    }

    private ProductBom bom(Long bomId, String status, Integer frozenFlag) {
        ProductBom bom = new ProductBom();
        bom.setProductBomId(bomId);
        bom.setProductId(20L);
        bom.setVersionNo("V1");
        bom.setCurrencyCode("CNY");
        bom.setStatus(status);
        bom.setFrozenFlag(frozenFlag);
        bom.setDeletedFlag(0);
        return bom;
    }

    private BomRouteSaveDTO route(Long processId, String code, List<String> colors) {
        BomRouteSaveDTO route = new BomRouteSaveDTO();
        route.setProcessId(processId);
        route.setRouteCode(code);
        route.setRouteName(code);
        route.setColors(colors);
        route.setItems(List.of(validItem()));
        return route;
    }

    private ProductBomItemDTO validItem() {
        ProductBomItemDTO item = new ProductBomItemDTO();
        item.setLineNo(1);
        item.setItemName("TPU");
        item.setQuantity(new BigDecimal("1"));
        item.setUnit("PCS");
        return item;
    }

    private ProcessRepository processRepository(Long processId, Long productId, String processCode, String processName) {
        ProcessRepository processRepository = mock(ProcessRepository.class);
        ProcessEntity process = new ProcessEntity();
        process.setProcessId(processId);
        process.setProductId(productId);
        process.setProcessType("routing");
        process.setProcessCode(processCode);
        process.setProcessName(processName);
        process.setStatus("confirmed");
        process.setDeletedFlag(0);
        when(processRepository.selectById(processId)).thenReturn(process);
        return processRepository;
    }

    private ProductBomRoute routeEntity(Long routeId, Long bomId, Long productId, Long processId) {
        ProductBomRoute route = new ProductBomRoute();
        route.setProductBomRouteId(routeId);
        route.setProductBomId(bomId);
        route.setProductId(productId);
        route.setProcessId(processId);
        route.setStatus("active");
        route.setDeletedFlag(0);
        return route;
    }

    private CodeItem color(Long id, String code, String name) {
        CodeItem item = new CodeItem();
        item.setCodeItemId(id);
        item.setCodeType("color");
        item.setCodeValue(code);
        item.setCodeName(name);
        item.setStatus("enabled");
        item.setDeletedFlag(0);
        return item;
    }
}
