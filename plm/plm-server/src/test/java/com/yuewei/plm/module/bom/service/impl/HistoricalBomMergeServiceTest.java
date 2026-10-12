package com.yuewei.plm.module.bom.service.impl;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper;
import com.yuewei.plm.module.bom.entity.ProductBom;
import com.yuewei.plm.module.bom.entity.ProductBomCostSnapshot;
import com.yuewei.plm.module.bom.entity.ProductBomItem;
import com.yuewei.plm.module.bom.entity.ProductBomRoute;
import com.yuewei.plm.module.bom.entity.ProductBomRouteColor;
import com.yuewei.plm.module.bom.entity.ProductBomRouteFormalSelection;
import com.yuewei.plm.module.bom.repository.ProductBomCostSnapshotRepository;
import com.yuewei.plm.module.bom.repository.ProductBomItemRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteColorRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteFormalSelectionRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteRepository;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import java.math.BigDecimal;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;

class HistoricalBomMergeServiceTest {

    @Test
    void analyzeMarksIdenticalRouteBomGroupAsAutoMergeable() {
        Fixture fixture = fixture(List.of(item(10L, 1L, "TPU-001", "TPU", 10)), List.of(item(20L, 2L, "TPU-001", "TPU", 10)));

        var result = fixture.service().analyze(100L);

        assertThat(result.getAnalyzedGroupCount()).isEqualTo(1);
        assertThat(result.getAutoMergeableGroupCount()).isEqualTo(1);
        assertThat(result.getCandidates().get(0).getCanAutoMerge()).isTrue();
        assertThat(result.getCandidates().get(0).getColors()).containsExactly("Negro", "Rojo");
        assertThat(result.getCandidates().get(0).getMainProductBomId()).isEqualTo(2L);
    }

    @Test
    void autoMergeCopiesMissingColorsAndArchivesSourceBom() {
        var first = item(10L, 1L, "TPU-001", "TPU", 10);
        var second = item(20L, 2L, "TPU-001", "TPU", 10);
        first.setUnitCostSnapshot(BigDecimal.ONE);second.setUnitCostSnapshot(BigDecimal.ONE);
        Fixture fixture = fixture(List.of(first), List.of(second));
        Mockito.doThrow(new com.yuewei.plm.common.exception.BusinessException(40103, "没有权限：finance:write")).when(fixture.access()).requireFinanceWrite();
        org.assertj.core.api.Assertions.assertThatThrownBy(() -> fixture.service().autoMerge(100L, null))
            .isInstanceOf(com.yuewei.plm.common.exception.BusinessException.class).hasMessageContaining("finance:write");
        Mockito.verify(fixture.boms(), Mockito.never()).updateById(any(ProductBom.class));
        Mockito.doNothing().when(fixture.access()).requireFinanceWrite();
        when(fixture.colors().selectList(Mockito.<Wrapper<ProductBomRouteColor>>any()))
            .thenReturn(List.of(color(10L, 1L, "02", "Negro"), color(20L, 2L, "07", "Rojo")))
            .thenReturn(List.of(color(20L, 2L, "07", "Rojo")));

        var result = fixture.service().autoMerge(100L, null);

        assertThat(result.getAutoMergedGroupCount()).isEqualTo(1);
        assertThat(result.getArchivedBomCount()).isEqualTo(1);
        ArgumentCaptor<ProductBom> bomCaptor = ArgumentCaptor.forClass(ProductBom.class);
        verify(fixture.boms(), Mockito.atLeast(2)).updateById(bomCaptor.capture());
        assertThat(bomCaptor.getAllValues()).anyMatch(bom -> Long.valueOf(1L).equals(bom.getProductBomId())
            && "archived".equals(bom.getStatus())
            && bom.getRemark().contains("mergedToProductBomId=2"));
        ArgumentCaptor<ProductBomRouteColor> colorCaptor = ArgumentCaptor.forClass(ProductBomRouteColor.class);
        verify(fixture.colors()).insert(colorCaptor.capture());
        assertThat(colorCaptor.getValue().getProductBomId()).isEqualTo(2L);
        assertThat(colorCaptor.getValue().getColorName()).isEqualTo("Negro");
        verify(fixture.selections()).insert(any(ProductBomRouteFormalSelection.class));
        verify(fixture.costs()).update(Mockito.isNull(), any(UpdateWrapper.class));
    }

    @Test
    void analyzeBlocksAutoMergeWhenColorRelatedItemsDiffer() {
        ProductBomItem commonA = item(10L, 1L, "TPU-001", "TPU", 10);
        ProductBomItem commonB = item(20L, 2L, "TPU-001", "TPU", 10);
        ProductBomItem blackPowder = item(11L, 1L, "COLOR-BLK", "color powder black", 20);
        ProductBomItem redPowder = item(21L, 2L, "COLOR-RED", "color powder red", 20);
        Fixture fixture = fixture(List.of(commonA, blackPowder), List.of(commonB, redPowder));

        var result = fixture.service().analyze(100L);

        assertThat(result.getCandidates()).hasSize(1);
        assertThat(result.getCandidates().get(0).getRiskLevel()).isEqualTo("medium");
        assertThat(result.getCandidates().get(0).getCanAutoMerge()).isFalse();
        assertThat(result.getCandidates().get(0).getReason()).contains("Color-related");
    }

    private Fixture fixture(List<ProductBomItem> firstItems, List<ProductBomItem> secondItems) {
        ProductRepository products = mock(ProductRepository.class);
        ProductBomRepository boms = mock(ProductBomRepository.class);
        ProductBomRouteRepository routes = mock(ProductBomRouteRepository.class);
        ProductBomRouteColorRepository colors = mock(ProductBomRouteColorRepository.class);
        ProductBomItemRepository items = mock(ProductBomItemRepository.class);
        ProductBomCostSnapshotRepository costs = mock(ProductBomCostSnapshotRepository.class);
        ProductBomRouteFormalSelectionRepository selections = mock(ProductBomRouteFormalSelectionRepository.class);
        OperationLogService logs = mock(OperationLogService.class);
        when(products.selectById(100L)).thenReturn(product());
        when(boms.selectList(Mockito.<Wrapper<ProductBom>>any())).thenReturn(List.of(bom(1L, "V1-02"), bom(2L, "V1-07")));
        when(routes.selectList(Mockito.<Wrapper<ProductBomRoute>>any())).thenReturn(List.of(route(1L, 1L), route(2L, 2L)));
        when(colors.selectList(Mockito.<Wrapper<ProductBomRouteColor>>any()))
            .thenReturn(List.of(color(10L, 1L, "02", "Negro"), color(20L, 2L, "07", "Rojo")))
            .thenReturn(List.of(color(20L, 2L, "07", "Rojo")));
        when(items.selectList(Mockito.<Wrapper<ProductBomItem>>any())).thenReturn(join(firstItems, secondItems));
        when(selections.selectList(Mockito.<Wrapper<ProductBomRouteFormalSelection>>any())).thenReturn(List.of());
        var access = BomImportServiceImplTest.access(true);
        HistoricalBomMergeService service = new HistoricalBomMergeService(products, boms, routes, colors, items, costs, selections, logs, access);
        return new Fixture(service, boms, colors, costs, selections, access);
    }

    private Product product() {
        Product product = new Product();
        product.setProductId(100L);
        product.setProductCode("NHA4030");
        product.setProductName("Super Capitan");
        return product;
    }

    private ProductBom bom(Long id, String versionNo) {
        ProductBom bom = new ProductBom();
        bom.setProductBomId(id);
        bom.setProductId(100L);
        bom.setBomCode("BOM-" + id);
        bom.setBomName("History BOM " + versionNo);
        bom.setBomType("mbom");
        bom.setBomScope("formal");
        bom.setVersionNo(versionNo);
        bom.setStatus("released");
        bom.setDeletedFlag(0);
        return bom;
    }

    private ProductBomRoute route(Long routeId, Long bomId) {
        ProductBomRoute route = new ProductBomRoute();
        route.setProductBomRouteId(routeId);
        route.setProductBomId(bomId);
        route.setProductId(100L);
        route.setProcessId(228L);
        route.setRouteCode("ROUTE-228");
        route.setRouteName("standard route");
        route.setRouteVariantNo("BASE");
        route.setStatus("active");
        route.setDeletedFlag(0);
        return route;
    }

    private ProductBomRouteColor color(Long colorId, Long routeId, String code, String name) {
        ProductBomRouteColor color = new ProductBomRouteColor();
        color.setProductBomRouteColorId(colorId);
        color.setProductBomId(routeId);
        color.setProductBomRouteId(routeId);
        color.setCodeItemId(colorId);
        color.setColorCode(code);
        color.setColorName(name);
        color.setStatus("active");
        color.setDeletedFlag(0);
        return color;
    }

    private ProductBomItem item(Long id, Long routeId, String code, String name, int lineNo) {
        ProductBomItem item = new ProductBomItem();
        item.setProductBomItemId(id);
        item.setProductBomRouteId(routeId);
        item.setProductBomId(routeId);
        item.setItemCode(code);
        item.setItemName(name);
        item.setLineNo(lineNo);
        item.setQuantity(BigDecimal.ONE);
        item.setUnit("pcs");
        item.setMaterialSource("inventory");
        item.setDeletedFlag(0);
        return item;
    }

    private List<ProductBomItem> join(List<ProductBomItem> first, List<ProductBomItem> second) {
        List<ProductBomItem> result = new java.util.ArrayList<>(first);
        result.addAll(second);
        return result;
    }

    private record Fixture(
        HistoricalBomMergeService service,
        ProductBomRepository boms,
        ProductBomRouteColorRepository colors,
        ProductBomCostSnapshotRepository costs,
        ProductBomRouteFormalSelectionRepository selections,
        com.yuewei.plm.module.pilot.PilotAccessService access
    ) {
    }
}
