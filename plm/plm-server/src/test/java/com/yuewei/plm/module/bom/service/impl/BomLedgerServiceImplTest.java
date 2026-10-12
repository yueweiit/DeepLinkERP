package com.yuewei.plm.module.bom.service.impl;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.never;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.module.bom.entity.ProductBom;
import com.yuewei.plm.module.bom.entity.ProductBomRoute;
import com.yuewei.plm.module.bom.entity.ProductBomRouteColor;
import com.yuewei.plm.module.bom.entity.ProductBomRouteFormalSelection;
import com.yuewei.plm.module.bom.entity.ProductBomCostSnapshot;
import com.yuewei.plm.module.bom.entity.ProductBomItem;
import com.yuewei.plm.module.bom.repository.ProductBomCostSnapshotRepository;
import com.yuewei.plm.module.bom.repository.ProductBomItemRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteColorRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteFormalSelectionRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteRepository;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import java.util.List;
import java.util.ArrayList;
import java.math.BigDecimal;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;

class BomLedgerServiceImplTest {

    @Test
    void detailQueriesEachRelationOnceRegardlessOfRouteCount() {
        ProductBomRepository boms = mock(ProductBomRepository.class);
        ProductBomRouteRepository routes = mock(ProductBomRouteRepository.class);
        ProductBomRouteColorRepository colors = mock(ProductBomRouteColorRepository.class);
        ProductBomItemRepository items = mock(ProductBomItemRepository.class);
        ProductBomCostSnapshotRepository costs = mock(ProductBomCostSnapshotRepository.class);
        BomLedgerServiceImpl service = new BomLedgerServiceImpl(mock(ProductRepository.class), boms, routes, colors,
            items, costs, mock(ProductBomRouteFormalSelectionRepository.class));
        when(boms.selectById(10L)).thenReturn(bom(10L, "formal", "released"));
        List<ProductBomRoute> routeValues = new ArrayList<>();
        List<ProductBomRouteColor> colorValues = new ArrayList<>();
        List<ProductBomItem> itemValues = new ArrayList<>();
        List<ProductBomCostSnapshot> costValues = new ArrayList<>();
        for (long id = 100; id < 120; id++) {
            routeValues.add(route(id, "R" + id)); colorValues.add(color(id, "02", "黑色"));
            ProductBomItem item = new ProductBomItem(); item.setProductBomId(10L); item.setProductBomRouteId(id);
            item.setItemName("Material"); item.setProductBomItemId(id); itemValues.add(item);
            ProductBomCostSnapshot cost = new ProductBomCostSnapshot();
            cost.setProductBomId(10L); cost.setProductBomRouteId(id); cost.setTotalCost(BigDecimal.ONE);
            costValues.add(cost);
        }
        when(routes.selectList(Mockito.<Wrapper<ProductBomRoute>>any())).thenReturn(routeValues);
        when(colors.selectList(Mockito.<Wrapper<ProductBomRouteColor>>any())).thenReturn(colorValues);
        when(items.selectList(Mockito.<Wrapper<ProductBomItem>>any())).thenReturn(itemValues);
        when(costs.selectList(Mockito.<Wrapper<ProductBomCostSnapshot>>any())).thenReturn(costValues);

        var detail = service.getWorkbench(10L);

        assertThat(detail.getRoutes()).hasSize(20).allSatisfy(value -> {
            assertThat(value.getItems()).hasSize(1);
            assertThat(value.getColors()).containsExactly("黑色");
            assertThat(value.getSkuUnitCost()).isEqualByComparingTo(BigDecimal.ONE);
        });
        assertThat(detail.getRdTotalCost()).isEqualByComparingTo("20");
        assertThat(detail.getFormalAverageUnitCost()).isEqualByComparingTo("1");
        verify(routes, times(1)).selectList(Mockito.<Wrapper<ProductBomRoute>>any());
        verify(colors, times(1)).selectList(Mockito.<Wrapper<ProductBomRouteColor>>any());
        verify(items, times(1)).selectList(Mockito.<Wrapper<ProductBomItem>>any());
        verify(costs, times(1)).selectList(Mockito.<Wrapper<ProductBomCostSnapshot>>any());
    }

    @Test
    void listStatisticsBatchProductsRoutesAndColorsWithoutLoadingDetailsOrCosts() {
        ProductRepository products = mock(ProductRepository.class);
        ProductBomRepository boms = mock(ProductBomRepository.class);
        ProductBomRouteRepository routes = mock(ProductBomRouteRepository.class);
        ProductBomRouteColorRepository colors = mock(ProductBomRouteColorRepository.class);
        ProductBomItemRepository items = mock(ProductBomItemRepository.class);
        ProductBomCostSnapshotRepository costs = mock(ProductBomCostSnapshotRepository.class);
        BomLedgerServiceImpl service = new BomLedgerServiceImpl(products, boms, routes, colors, items, costs,
            mock(ProductBomRouteFormalSelectionRepository.class));
        List<ProductBom> values = new ArrayList<>(); List<ProductBomRoute> routeValues = new ArrayList<>();
        List<ProductBomRouteColor> colorValues = new ArrayList<>();
        for (long id = 10; id < 40; id++) {
            values.add(bom(id, "formal", "released"));
            ProductBomRoute route = route(id + 100, "R" + id); route.setProductBomId(id); routeValues.add(route);
            colorValues.add(color(id + 100, "蓝色"));
        }
        when(routes.selectList(Mockito.<Wrapper<ProductBomRoute>>any())).thenReturn(routeValues);
        when(colors.selectList(Mockito.<Wrapper<ProductBomRouteColor>>any())).thenReturn(colorValues);
        when(products.selectList(Mockito.<Wrapper<Product>>any())).thenReturn(List.of(product(1L, null, null), product(2L, 1L, "蓝色")));

        var rows = service.describeFormal(values);

        assertThat(rows).hasSize(30).allSatisfy(value -> {
            assertThat(value.getRouteCount()).isEqualTo(1); assertThat(value.getSkuCount()).isEqualTo(1);
            assertThat(value.getProductCode()).isEqualTo("SKU-1");
        });
        verify(routes, times(1)).selectList(Mockito.<Wrapper<ProductBomRoute>>any());
        verify(colors, times(1)).selectList(Mockito.<Wrapper<ProductBomRouteColor>>any());
        verify(products, times(1)).selectList(Mockito.<Wrapper<Product>>any());
        verify(items, never()).selectList(Mockito.<Wrapper<ProductBomItem>>any());
        verify(costs, never()).selectList(Mockito.<Wrapper<ProductBomCostSnapshot>>any());
    }

    @Test
    void ledgerReturnsFormalBomsOnly() {
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProductRepository productRepository = mock(ProductRepository.class);
        ProductBomRouteFormalSelectionRepository formalSelectionRepository = mock(ProductBomRouteFormalSelectionRepository.class);
        BomLedgerServiceImpl service = service(bomRepository, productRepository, formalSelectionRepository);
        ProductBom formal = bom(10L, "formal", "released");
        ProductBom unselectedCandidate = bom(11L, "candidate", "released");
        ProductBom draft = bom(12L, "formal", "draft");
        ProductBom test = bom(13L, "test", "confirmed");
        ProductBom unselectedFormal = bom(14L, "formal", "released");
        ProductBom historicalImport = bom(15L, "formal", "released");
        historicalImport.setSourceType("import");
        when(bomRepository.selectList(Mockito.<Wrapper<ProductBom>>any()))
            .thenReturn(List.of(formal, unselectedCandidate, draft, test, unselectedFormal, historicalImport));
        when(formalSelectionRepository.selectList(Mockito.<Wrapper<ProductBomRouteFormalSelection>>any()))
            .thenReturn(List.of(formalSelection(10L)));
        when(productRepository.selectById(1L)).thenReturn(product(1L, null, "蓝色"));

        var rows = service.listFormal();

        assertThat(rows).extracting("productBomId").containsExactly(10L, 15L);
    }

    @Test
    void skuColorConflictIsReportedInsteadOfChoosingFirstRoute() {
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProductRepository productRepository = mock(ProductRepository.class);
        ProductBomRouteRepository routeRepository = mock(ProductBomRouteRepository.class);
        ProductBomRouteColorRepository colorRepository = mock(ProductBomRouteColorRepository.class);
        BomLedgerServiceImpl service = new BomLedgerServiceImpl(
            productRepository, bomRepository, routeRepository, colorRepository,
            mock(ProductBomItemRepository.class), mock(ProductBomCostSnapshotRepository.class),
            mock(ProductBomRouteFormalSelectionRepository.class)
        );
        when(bomRepository.selectById(10L)).thenReturn(bom(10L, "formal", "released"));
        when(productRepository.selectList(Mockito.<Wrapper<Product>>any()))
            .thenReturn(List.of(product(2L, 1L, "蓝色")));
        when(routeRepository.selectList(Mockito.<Wrapper<ProductBomRoute>>any()))
            .thenReturn(List.of(route(100L, "DYE"), route(101L, "PRINT")));
        when(colorRepository.selectList(Mockito.<Wrapper<ProductBomRouteColor>>any()))
            .thenReturn(List.of(color(100L, "蓝色"), color(101L, "蓝色")));

        assertThatThrownBy(() -> service.listSkus(10L))
            .isInstanceOf(BusinessException.class)
            .hasMessageContaining("蓝色");
    }

    @Test
    void skuMatchesRouteByColorCodeWhenColorNamesDiffer() {
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProductRepository productRepository = mock(ProductRepository.class);
        ProductBomRouteRepository routeRepository = mock(ProductBomRouteRepository.class);
        ProductBomRouteColorRepository colorRepository = mock(ProductBomRouteColorRepository.class);
        BomLedgerServiceImpl service = new BomLedgerServiceImpl(
            productRepository, bomRepository, routeRepository, colorRepository,
            mock(ProductBomItemRepository.class), mock(ProductBomCostSnapshotRepository.class),
            mock(ProductBomRouteFormalSelectionRepository.class)
        );
        when(bomRepository.selectById(10L)).thenReturn(bom(10L, "formal", "released"));
        Product sku = product(2L, 1L, "黑色");
        sku.setColorCode("02");
        when(productRepository.selectList(Mockito.<Wrapper<Product>>any())).thenReturn(List.of(sku));
        when(routeRepository.selectList(Mockito.<Wrapper<ProductBomRoute>>any()))
            .thenReturn(List.of(route(100L, "DYE")));
        when(colorRepository.selectList(Mockito.<Wrapper<ProductBomRouteColor>>any()))
            .thenReturn(List.of(color(100L, "02", "Negro")));

        var rows = service.listSkus(10L);

        assertThat(rows).hasSize(1);
        assertThat(rows.get(0).getProductBomRouteId()).isEqualTo(100L);
        assertThat(rows.get(0).getRouteCode()).isEqualTo("DYE");
    }

    private BomLedgerServiceImpl service(ProductBomRepository bomRepository, ProductRepository productRepository,
                                         ProductBomRouteFormalSelectionRepository formalSelectionRepository) {
        return new BomLedgerServiceImpl(
            productRepository, bomRepository, mock(ProductBomRouteRepository.class),
            mock(ProductBomRouteColorRepository.class), mock(ProductBomItemRepository.class),
            mock(ProductBomCostSnapshotRepository.class), formalSelectionRepository
        );
    }

    private ProductBom bom(Long id, String scope, String status) {
        ProductBom bom = new ProductBom();
        bom.setProductBomId(id);
        bom.setProductId(1L);
        bom.setBomScope(scope);
        bom.setStatus(status);
        bom.setDeletedFlag(0);
        return bom;
    }

    private Product product(Long id, Long parentId, String color) {
        Product product = new Product();
        product.setProductId(id);
        product.setParentProductId(parentId);
        product.setProductCode("SKU-" + id);
        product.setProductName("亮甲 2.0");
        product.setModel("iPhone 18");
        product.setColor(color);
        product.setStatus("developing");
        product.setDeletedFlag(0);
        return product;
    }

    private ProductBomRoute route(Long id, String code) {
        ProductBomRoute route = new ProductBomRoute();
        route.setProductBomRouteId(id);
        route.setProductBomId(10L);
        route.setRouteCode(code);
        route.setStatus("active");
        route.setDeletedFlag(0);
        return route;
    }

    private ProductBomRouteColor color(Long routeId, String name) {
        ProductBomRouteColor color = new ProductBomRouteColor();
        color.setProductBomRouteId(routeId);
        color.setColorName(name);
        color.setStatus("active");
        color.setDeletedFlag(0);
        return color;
    }

    private ProductBomRouteColor color(Long routeId, String code, String name) {
        ProductBomRouteColor color = color(routeId, name);
        color.setColorCode(code);
        return color;
    }

    private ProductBomRouteFormalSelection formalSelection(Long bomId) {
        ProductBomRouteFormalSelection value = new ProductBomRouteFormalSelection();
        value.setProductId(1L);
        value.setProductBomId(bomId);
        value.setProductBomRouteId(100L);
        value.setProcessId(200L);
        value.setStatus("active");
        value.setDeletedFlag(0);
        return value;
    }
}
