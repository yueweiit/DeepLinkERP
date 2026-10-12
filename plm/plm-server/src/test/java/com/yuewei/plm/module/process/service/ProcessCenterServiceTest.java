package com.yuewei.plm.module.process.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.module.bom.entity.ProductBomRoute;
import com.yuewei.plm.module.bom.entity.ProductBomRouteColor;
import com.yuewei.plm.module.bom.repository.ProductBomRouteColorRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteRepository;
import com.yuewei.plm.module.process.entity.ProcessEntity;
import com.yuewei.plm.module.process.repository.ProcessRepository;
import com.yuewei.plm.module.process.service.impl.ProcessCenterServiceImpl;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class ProcessCenterServiceTest {
    private ProductRepository productRepository;
    private ProcessRepository processRepository;
    private ProductBomRouteRepository bomRouteRepository;
    private ProductBomRouteColorRepository bomRouteColorRepository;
    private ProcessCenterService service;

    @BeforeEach
    void setUp() {
        productRepository = mock(ProductRepository.class);
        processRepository = mock(ProcessRepository.class);
        bomRouteRepository = mock(ProductBomRouteRepository.class);
        bomRouteColorRepository = mock(ProductBomRouteColorRepository.class);
        service = new ProcessCenterServiceImpl(productRepository, processRepository, bomRouteRepository,
            bomRouteColorRepository, new ObjectMapper());
    }

    @Test
    void snapshotAggregatesRoutesColorsAndSkuCounts() {
        ProcessEntity route = route(81L, 7L);
        Product product = product(7L, null, "product_line", null);
        Product sku = product(91L, 7L, "sku", "蓝色");
        when(processRepository.selectList(any(Wrapper.class))).thenReturn(List.of(route), List.of(operation(811L, 81L)));
        when(productRepository.selectBatchIds(any())).thenReturn(List.of(product));
        when(bomRouteRepository.selectList(any(Wrapper.class))).thenReturn(List.of(bomRoute(301L, 81L)));
        when(bomRouteColorRepository.selectList(any(Wrapper.class))).thenReturn(List.of(color(301L, "02", "蓝色")));
        when(productRepository.selectList(any(Wrapper.class))).thenReturn(List.of(sku));

        var snapshot = service.snapshot();

        assertThat(snapshot.getRoutes()).hasSize(1);
        assertThat(snapshot.getRoutes().get(0).getRouteId()).isEqualTo(81L);
        assertThat(snapshot.getRoutes().get(0).getColors()).extracting("colorName").containsExactly("蓝色");
        assertThat(snapshot.getRoutes().get(0).getSkuCount()).isEqualTo(1);
        assertThat(snapshot.getRouteDetails()).containsKey(81L);
    }

    @Test
    void relationsReturnsColorsSkusAndOperationsByProcessRoute() {
        ProcessEntity route = route(81L, 7L);
        Product product = product(7L, null, "product_line", null);
        Product sku = product(91L, 7L, "sku", "蓝色");
        when(processRepository.selectById(81L)).thenReturn(route);
        when(productRepository.selectById(7L)).thenReturn(product);
        when(processRepository.selectList(any(Wrapper.class))).thenReturn(List.of(operation(811L, 81L)));
        when(bomRouteRepository.selectList(any(Wrapper.class))).thenReturn(List.of(bomRoute(301L, 81L)));
        when(bomRouteColorRepository.selectList(any(Wrapper.class))).thenReturn(List.of(color(301L, "02", "蓝色")));
        when(productRepository.selectList(any(Wrapper.class))).thenReturn(List.of(sku));

        var relation = service.relations(81L);

        assertThat(relation.getProcessId()).isEqualTo(81L);
        assertThat(relation.getColors()).extracting("colorName").containsExactly("蓝色");
        assertThat(relation.getSkus()).extracting("skuCode").containsExactly("SKU-91");
        assertThat(relation.getOperations()).extracting("processName").containsExactly("喷涂");
    }

    @Test
    void relationsMatchesSkuByColorCodeWhenColorNamesDiffer() {
        ProcessEntity route = route(82L, 8L);
        Product product = product(8L, null, "product_line", null);
        Product sku = product(92L, 8L, "sku", "黑色");
        sku.setColorCode("02");
        when(processRepository.selectById(82L)).thenReturn(route);
        when(productRepository.selectById(8L)).thenReturn(product);
        when(processRepository.selectList(any(Wrapper.class))).thenReturn(List.of());
        when(bomRouteRepository.selectList(any(Wrapper.class))).thenReturn(List.of(bomRoute(302L, 82L)));
        when(bomRouteColorRepository.selectList(any(Wrapper.class))).thenReturn(List.of(color(302L, "02", "Negro")));
        when(productRepository.selectList(any(Wrapper.class))).thenReturn(List.of(sku));

        var relation = service.relations(82L);

        assertThat(relation.getSkus()).extracting("skuCode").containsExactly("SKU-92");
        assertThat(relation.getSkus().get(0).getRouteCode()).isEqualTo("DYE");
    }

    private ProcessEntity route(Long processId, Long productId) {
        ProcessEntity value = new ProcessEntity();
        value.setProcessId(processId);
        value.setProductId(productId);
        value.setProcessCode("ROUTE-" + processId);
        value.setProcessName("染色工艺路线");
        value.setProcessType("routing");
        value.setVersionNo("V1");
        value.setStatus("locked");
        value.setProcessParamJson("{\"routeTemplateCode\":\"ROUTE-STD\"}");
        value.setDeletedFlag(0);
        return value;
    }

    private ProcessEntity operation(Long processId, Long parentProcessId) {
        ProcessEntity value = new ProcessEntity();
        value.setProcessId(processId);
        value.setParentProcessId(parentProcessId);
        value.setProcessCode("OP-" + processId);
        value.setProcessName("喷涂");
        value.setProcessType("operation");
        value.setSequenceNo(1);
        value.setQualityRequirement("颜色一致");
        value.setStatus("locked");
        value.setDeletedFlag(0);
        return value;
    }

    private Product product(Long productId, Long parentProductId, String productType, String color) {
        Product value = new Product();
        value.setProductId(productId);
        value.setParentProductId(parentProductId);
        value.setProductCode("sku".equals(productType) ? "SKU-" + productId : "PRD-" + productId);
        value.setProductName("亮甲 2.0");
        value.setProductType(productType);
        value.setModel("Samsung A56");
        value.setColor(color);
        value.setStatus("released");
        value.setDeletedFlag(0);
        return value;
    }

    private ProductBomRoute bomRoute(Long productBomRouteId, Long processId) {
        ProductBomRoute value = new ProductBomRoute();
        value.setProductBomRouteId(productBomRouteId);
        value.setProductBomId(31L);
        value.setProductId(7L);
        value.setProcessId(processId);
        value.setRouteCode("DYE");
        value.setRouteName("染色 BOM 路线");
        value.setStatus("active");
        value.setDeletedFlag(0);
        return value;
    }

    private ProductBomRouteColor color(Long productBomRouteId, String colorCode, String colorName) {
        ProductBomRouteColor value = new ProductBomRouteColor();
        value.setProductBomRouteId(productBomRouteId);
        value.setCodeItemId(2L);
        value.setColorCode(colorCode);
        value.setColorName(colorName);
        value.setStatus("active");
        value.setDeletedFlag(0);
        return value;
    }
}
