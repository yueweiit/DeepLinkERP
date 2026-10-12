package com.yuewei.plm.module.process.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.yuewei.plm.module.bom.entity.ProductBom;
import com.yuewei.plm.module.bom.entity.ProductBomRoute;
import com.yuewei.plm.module.bom.entity.ProductBomRouteColor;
import com.yuewei.plm.module.bom.repository.ProductBomRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteColorRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteRepository;
import com.yuewei.plm.module.process.entity.ProcessEntity;
import com.yuewei.plm.module.process.repository.ProcessRepository;
import com.yuewei.plm.repository.entity.Product;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;

class ProcessRouteInheritanceServiceTest {

    @Test
    void copiesFormalBomReferencedRouteAndOperationsBySelectedColors() {
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProductBomRouteRepository bomRouteRepository = mock(ProductBomRouteRepository.class);
        ProductBomRouteColorRepository colorRepository = mock(ProductBomRouteColorRepository.class);
        ProcessRepository processRepository = mock(ProcessRepository.class);
        ProcessRouteInheritanceService service = new ProcessRouteInheritanceService(
            bomRepository, bomRouteRepository, colorRepository, processRepository);

        ProductBom bom = new ProductBom();
        bom.setProductBomId(10L);
        when(bomRepository.selectList(Mockito.<Wrapper<ProductBom>>any())).thenReturn(List.of(bom));
        ProductBomRoute bomRoute = new ProductBomRoute();
        bomRoute.setProductBomRouteId(11L);
        bomRoute.setProcessId(27L);
        when(bomRouteRepository.selectList(Mockito.<Wrapper<ProductBomRoute>>any())).thenReturn(List.of(bomRoute));
        ProductBomRouteColor color = new ProductBomRouteColor();
        color.setColorName("黑色");
        when(colorRepository.selectList(Mockito.<Wrapper<ProductBomRouteColor>>any())).thenReturn(List.of(color));

        ProcessEntity sourceRoute = route(27L, "PRD-PARENT-ROUTE-V1", "routing", null, 1);
        sourceRoute.setProcessName("标准注塑组装路线");
        ProcessEntity sourceOperation = route(28L, "PRD-PARENT-ROUTE-V1-OP10", "operation", 27L, 10);
        sourceOperation.setOperationCraftCode("4030");
        when(processRepository.selectById(27L)).thenReturn(sourceRoute);
        when(processRepository.selectList(Mockito.<Wrapper<ProcessEntity>>any())).thenReturn(List.of(sourceOperation));
        when(processRepository.selectCount(Mockito.<Wrapper<ProcessEntity>>any())).thenReturn(0L);
        Mockito.doAnswer(invocation -> {
            ProcessEntity entity = invocation.getArgument(0);
            if ("routing".equals(entity.getProcessType())) {
                entity.setProcessId(200L);
            } else {
                entity.setProcessId(201L);
            }
            return 1;
        }).when(processRepository).insert(Mockito.any(ProcessEntity.class));

        Product target = new Product();
        target.setProductId(5L);
        target.setProductCode("PRD-超队30IP-0002");
        target.setProductType("model_variant");
        target.setProductSpecificCode("HD");
        target.setModel("iphone 18");
        target.setPhoneModelCode("1801");
        target.setColorCode("02");

        Map<Long, Long> mapping = service.inheritLatestReleasedFormalBomRoutesByColors(1L, target, List.of("黑色"), "engineer");

        assertThat(mapping).containsEntry(27L, 200L);
        ArgumentCaptor<ProcessEntity> captor = ArgumentCaptor.forClass(ProcessEntity.class);
        verify(processRepository, Mockito.times(2)).insert(captor.capture());
        assertThat(captor.getAllValues().get(0).getProductId()).isEqualTo(5L);
        assertThat(captor.getAllValues().get(0).getProcessType()).isEqualTo("routing");
        assertThat(captor.getAllValues().get(0).getStatus()).isEqualTo("confirmed");
        assertThat(captor.getAllValues().get(0).getProcessCode()).isEqualTo("PRD-30IP-0002-0000-I");
        assertThat(captor.getAllValues().get(0).getProcessName()).isEqualTo("标准注塑组装路线 - iphone 18");
        assertThat(captor.getAllValues().get(1).getParentProcessId()).isEqualTo(200L);
        assertThat(captor.getAllValues().get(1).getProductId()).isEqualTo(5L);
        assertThat(captor.getAllValues().get(1).getStatus()).isEqualTo("confirmed");
        assertThat(captor.getAllValues().get(1).getProcessName()).isEqualTo(sourceOperation.getProcessName());
        assertThat(captor.getAllValues().get(1).getOperationCraftCode()).isEqualTo("4030");
        assertThat(captor.getAllValues().get(1).getBusinessOperationCode()).isEqualTo("NHD40301801");
        assertThat(captor.getAllValues().get(1).getGeneratedFinishedProductCode()).isEqualTo("NHD40301801");
    }

    private ProcessEntity route(Long id, String code, String type, Long parentId, Integer sequenceNo) {
        ProcessEntity value = new ProcessEntity();
        value.setProcessId(id);
        value.setParentProcessId(parentId);
        value.setProductId(1L);
        value.setProcessCode(code);
        value.setProcessName(code);
        value.setProcessType(type);
        value.setVersionNo("V1");
        value.setSequenceNo(sequenceNo);
        value.setQualityRequirement("OK");
        value.setStatus("locked");
        value.setDeletedFlag(0);
        return value;
    }
}
