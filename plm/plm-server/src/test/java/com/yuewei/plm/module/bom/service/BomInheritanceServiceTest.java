package com.yuewei.plm.module.bom.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.yuewei.plm.module.bom.entity.ProductBom;
import com.yuewei.plm.module.bom.entity.ProductBomItem;
import com.yuewei.plm.module.bom.entity.ProductBomRoute;
import com.yuewei.plm.module.bom.entity.ProductBomRouteColor;
import com.yuewei.plm.module.bom.repository.ProductBomCostSnapshotRepository;
import com.yuewei.plm.module.bom.repository.ProductBomItemRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteColorRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteRepository;
import com.yuewei.plm.module.process.repository.ProcessRepository;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.BeforeEach;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;

class BomInheritanceServiceTest {
    ProductRepository productRepository;ProductBomRepository bomRepository;ProductBomRouteRepository routeRepository;
    ProductBomRouteColorRepository colorRepository;ProductBomItemRepository itemRepository;ProductBomCostSnapshotRepository costRepository;
    ProcessRepository processRepository;BomInheritanceService service;ProductBom source;

    @BeforeEach
    void sourceFixture() {
        productRepository = mock(ProductRepository.class);
        bomRepository = mock(ProductBomRepository.class);
        routeRepository = mock(ProductBomRouteRepository.class);
        colorRepository = mock(ProductBomRouteColorRepository.class);
        itemRepository = mock(ProductBomItemRepository.class);
        costRepository = mock(ProductBomCostSnapshotRepository.class);
        processRepository = mock(ProcessRepository.class);
        service = new BomInheritanceService(
            productRepository, bomRepository, routeRepository, colorRepository, itemRepository, costRepository,
            processRepository
        );
        source = new ProductBom();
        source.setProductBomId(10L);
        source.setProductId(1L);
        source.setBomName("产品线正式 BOM");
        source.setVersionNo("V1");
        source.setStatus("released");
        source.setBomScope("formal");
        source.setCurrencyCode("CNY");
        source.setDeletedFlag(0);
        Product target = new Product();
        target.setProductId(2L);
        target.setDeletedFlag(0);
        ProductBomRoute dye = route(100L, 10L, 1000L, "DYE");
        ProductBomRoute clear = route(101L, 10L, 1001L, "CLEAR");
        when(productRepository.selectById(2L)).thenReturn(target);
        Product owner=new Product();owner.setProductId(1L);owner.setDeletedFlag(0);when(productRepository.selectById(1L)).thenReturn(owner);
        when(bomRepository.selectById(10L)).thenReturn(source);
        when(routeRepository.selectList(Mockito.<Wrapper<ProductBomRoute>>any())).thenReturn(List.of(dye, clear));
        when(colorRepository.selectList(Mockito.<Wrapper<ProductBomRouteColor>>any()))
            .thenReturn(List.of(color(100L, "黑色"), color(100L, "蓝色")), List.of(color(101L, "透明色")));
        when(itemRepository.selectList(Mockito.<Wrapper<ProductBomItem>>any())).thenReturn(List.of(), List.of());
        when(bomRepository.insert(any(ProductBom.class))).thenAnswer(invocation -> {
            ProductBom value = invocation.getArgument(0);
            value.setProductBomId(20L);
            return 1;
        });
        when(routeRepository.insert(any(ProductBomRoute.class))).thenAnswer(invocation -> {
            ProductBomRoute value = invocation.getArgument(0);
            value.setProductBomRouteId(200L);
            return 1;
        });
    }

    @Test
    void copiesOnlySelectedColorsIntoTargetDraftWithoutUpdatingSource() {
        ProductBom inherited = service.inherit(10L, 2L, List.of("蓝色"));

        assertThat(inherited.getProductId()).isEqualTo(2L);
        assertThat(inherited.getSourceProductBomId()).isEqualTo(10L);
        assertThat(inherited.getStatus()).isEqualTo("draft");
        assertThat(inherited.getBomScope()).isEqualTo("candidate");
        ArgumentCaptor<ProductBomRouteColor> colorCaptor = ArgumentCaptor.forClass(ProductBomRouteColor.class);
        verify(colorRepository).insert(colorCaptor.capture());
        assertThat(colorCaptor.getValue().getColorName()).isEqualTo("蓝色");
        verify(routeRepository).insert(any(ProductBomRoute.class));
        verify(bomRepository, never()).updateById(source);
    }

    @Test void copyVersionStartsAsAnUnpublishedCandidateAndNeverChangesTheReleasedSource() {
        ProductBom copied=service.copyVersion(10L,"V2",List.of("蓝色"));
        assertThat(copied.getProductId()).isEqualTo(1L);assertThat(copied.getVersionNo()).isEqualTo("V2");assertThat(copied.getBomScope()).isEqualTo("candidate");assertThat(copied.getStatus()).isEqualTo("draft");assertThat(copied.getConfirmedAt()).isNull();assertThat(copied.getReleasedAt()).isNull();
        assertThat(source.getStatus()).isEqualTo("released");assertThat(source.getBomScope()).isEqualTo("formal");assertThat(source.getVersionNo()).isEqualTo("V1");verify(bomRepository,never()).updateById(any(ProductBom.class));
        var copiedRoute=ArgumentCaptor.forClass(ProductBomRoute.class);verify(routeRepository).insert(copiedRoute.capture());assertThat(copiedRoute.getValue().getSourceProductBomRouteId()).isEqualTo(100L);
    }

    private ProductBomRoute route(Long routeId, Long bomId, Long processId, String code) {
        ProductBomRoute route = new ProductBomRoute();
        route.setProductBomRouteId(routeId);
        route.setProductBomId(bomId);
        route.setProcessId(processId);
        route.setRouteCode(code);
        route.setRouteName(code);
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
}
