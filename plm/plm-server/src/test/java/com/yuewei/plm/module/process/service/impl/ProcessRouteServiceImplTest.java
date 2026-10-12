package com.yuewei.plm.module.process.service.impl;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.bom.repository.ProductBomRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteRepository;
import com.yuewei.plm.module.process.dto.ProcessOperationDTO;
import com.yuewei.plm.module.process.dto.ProcessRouteSaveDTO;
import com.yuewei.plm.module.process.entity.ProcessEntity;
import com.yuewei.plm.module.process.repository.ProcessRepository;
import com.yuewei.plm.module.process.service.ProcessRouteTemplateService;
import com.yuewei.plm.module.process.vo.ProcessRouteTemplateOperationVO;
import com.yuewei.plm.module.process.vo.ProcessRouteTemplateVO;
import com.yuewei.plm.module.process.vo.ProcessRouteVO;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;

class ProcessRouteServiceImplTest {

    @Test
    void duplicateSequenceNoRejectsCreate() {
        ProductRepository productRepository = mock(ProductRepository.class);
        when(productRepository.selectById(10L)).thenReturn(product(10L));
        ProcessRouteServiceImpl service = new ProcessRouteServiceImpl(
            productRepository,
            mock(ProcessRepository.class),
            mock(ProductBomRepository.class),
            mock(ProductBomRouteRepository.class),
            mock(OperationLogService.class),
            mock(ProcessRouteTemplateService.class),
            new ObjectMapper()
        );

        assertThatThrownBy(() -> service.create(10L, routeDTO(operation(10, "{}"), operation(10, "{}")), null))
            .isInstanceOf(BusinessException.class)
            .extracting("code")
            .isEqualTo(ErrorCodeConstants.CODE_CONFLICT);
    }

    @Test
    void invalidParamJsonRejectsCreate() {
        ProductRepository productRepository = mock(ProductRepository.class);
        when(productRepository.selectById(10L)).thenReturn(product(10L));
        ProcessRouteServiceImpl service = new ProcessRouteServiceImpl(
            productRepository,
            mock(ProcessRepository.class),
            mock(ProductBomRepository.class),
            mock(ProductBomRouteRepository.class),
            mock(OperationLogService.class),
            mock(ProcessRouteTemplateService.class),
            new ObjectMapper()
        );

        assertThatThrownBy(() -> service.create(10L, routeDTO(operation(10, "{bad-json")), null))
            .isInstanceOf(BusinessException.class)
            .extracting("code")
            .isEqualTo(ErrorCodeConstants.VALIDATION_ERROR);
    }

    @Test
    void finalSelectedCreateStoresRouteAndOperationsAsConfirmed() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProcessRepository processRepository = mock(ProcessRepository.class);
        List<ProcessEntity> stored = new ArrayList<>();
        AtomicLong idSequence = new AtomicLong(100L);
        when(productRepository.selectById(10L)).thenReturn(product(10L));
        when(processRepository.insert(Mockito.any(ProcessEntity.class))).thenAnswer(invocation -> {
            ProcessEntity entity = invocation.getArgument(0);
            entity.setProcessId(idSequence.getAndIncrement());
            stored.add(entity);
            return 1;
        });
        when(processRepository.selectById(Mockito.anyLong())).thenAnswer(invocation -> stored.stream()
            .filter(entity -> entity.getProcessId().equals(invocation.getArgument(0)))
            .findFirst()
            .orElse(null));
        when(processRepository.selectList(Mockito.<Wrapper<ProcessEntity>>any())).thenAnswer(invocation -> stored.stream()
            .filter(entity -> "operation".equals(entity.getProcessType()))
            .filter(entity -> Integer.valueOf(0).equals(entity.getDeletedFlag()))
            .toList());
        ProcessRouteServiceImpl service = new ProcessRouteServiceImpl(
            productRepository,
            processRepository,
            mock(ProductBomRepository.class),
            mock(ProductBomRouteRepository.class),
            mock(OperationLogService.class),
            mock(ProcessRouteTemplateService.class),
            new ObjectMapper()
        );

        ProcessRouteSaveDTO dto = routeDTO(operation(10, "{}"));
        dto.setFinalSelected(true);

        ProcessRouteVO result = service.create(10L, dto, null);

        assertThat(result.getStatus()).isEqualTo("confirmed");
        assertThat(result.getOperations()).extracting("status").containsExactly("confirmed");
    }

    @Test
    void lockedRouteRejectsDirectUpdate() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProcessRepository processRepository = mock(ProcessRepository.class);
        ProcessEntity route = new ProcessEntity();
        route.setProcessId(100L);
        route.setProductId(10L);
        route.setProcessType("routing");
        route.setProcessCode("P10-ROUTE-001");
        route.setProcessName("测试路线");
        route.setVersionNo("V1");
        route.setStatus("locked");
        route.setDeletedFlag(0);
        when(productRepository.selectById(10L)).thenReturn(product(10L));
        when(processRepository.selectById(100L)).thenReturn(route);
        ProcessRouteServiceImpl service = new ProcessRouteServiceImpl(
            productRepository,
            processRepository,
            mock(ProductBomRepository.class),
            mock(ProductBomRouteRepository.class),
            mock(OperationLogService.class),
            mock(ProcessRouteTemplateService.class),
            new ObjectMapper()
        );

        assertThatThrownBy(() -> service.update(100L, routeDTO(operation(10, "{}")), null))
            .isInstanceOf(BusinessException.class)
            .hasMessageContaining("不能直接编辑");
    }

    @Test
    void confirmedRouteAllowsUpdateAndKeepsOperationsConfirmed() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProcessRepository processRepository = mock(ProcessRepository.class);
        List<ProcessEntity> stored = new ArrayList<>();
        AtomicLong idSequence = new AtomicLong(300L);

        Product product = product(55L, "NWV4030");
        product.setProductType("product_line");
        product.setProductSpecificCode("WV");
        ProcessEntity route = new ProcessEntity();
        route.setProcessId(172L);
        route.setProductId(55L);
        route.setProcessCode("NWV4030-CUSTOM-A");
        route.setProcessName("waves薇武士 工艺路线");
        route.setProcessType("routing");
        route.setVersionNo("A");
        route.setStatus("confirmed");
        route.setDeletedFlag(0);
        ProcessEntity oldOperation = new ProcessEntity();
        oldOperation.setProcessId(284L);
        oldOperation.setParentProcessId(172L);
        oldOperation.setProcessType("operation");
        oldOperation.setBusinessOperationCode("NWV4030000000");
        oldOperation.setDeletedFlag(0);
        ProcessEntity master = operationMaster(900L, "PROC_" + "X".repeat(100), "组装", "{\"operationCraftCode\":\"4030\"}");
        stored.add(route);
        stored.add(oldOperation);

        when(productRepository.selectById(55L)).thenReturn(product);
        when(processRepository.selectById(Mockito.anyLong())).thenAnswer(invocation -> {
            Long id = invocation.getArgument(0);
            if (id.equals(900L)) {
                return master;
            }
            return stored.stream()
                .filter(entity -> id.equals(entity.getProcessId()))
                .findFirst()
                .orElse(null);
        });
        when(processRepository.selectCount(Mockito.<Wrapper<ProcessEntity>>any())).thenReturn(0L);
        when(processRepository.updateById(Mockito.any(ProcessEntity.class))).thenReturn(1);
        when(processRepository.update(Mockito.isNull(), Mockito.<Wrapper<ProcessEntity>>any())).thenAnswer(invocation -> {
            oldOperation.setDeletedFlag(1);
            return 1;
        });
        when(processRepository.insert(Mockito.any(ProcessEntity.class))).thenAnswer(invocation -> {
            ProcessEntity entity = invocation.getArgument(0);
            entity.setProcessId(idSequence.getAndIncrement());
            stored.add(entity);
            return 1;
        });
        when(processRepository.selectList(Mockito.<Wrapper<ProcessEntity>>any())).thenAnswer(invocation -> stored.stream()
            .filter(entity -> "operation".equals(entity.getProcessType()))
            .filter(entity -> Integer.valueOf(0).equals(entity.getDeletedFlag()))
            .toList());
        ProcessRouteServiceImpl service = new ProcessRouteServiceImpl(
            productRepository,
            processRepository,
            mock(ProductBomRepository.class),
            mock(ProductBomRouteRepository.class),
            mock(OperationLogService.class),
            mock(ProcessRouteTemplateService.class),
            new ObjectMapper()
        );

        ProcessOperationDTO operation = operation(30, "{}");
        operation.setOperationMasterProcessId(900L);
        operation.setOperationCraftCode("4030");
        operation.setFinishedProductFlag(true);

        ProcessRouteVO result = service.update(172L, routeDTO(operation), null);

        assertThat(oldOperation.getDeletedFlag()).isEqualTo(1);
        assertThat(result.getOperations()).hasSize(1);
        assertThat(result.getOperations().get(0).getStatus()).isEqualTo("confirmed");
        assertThat(result.getOperations().get(0).getProcessCode()).hasSizeLessThanOrEqualTo(64);
        assertThat(result.getOperations().get(0).getBusinessOperationCode()).isEqualTo("NWV4030");
        assertThat(result.getOperations().get(0).getGeneratedFinishedProductCode()).isEqualTo("NWV4030");
    }

    @Test
    void freezeRequiresOperations() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProcessRepository processRepository = mock(ProcessRepository.class);
        ProcessEntity route = new ProcessEntity();
        route.setProcessId(100L);
        route.setProductId(10L);
        route.setProcessType("routing");
        route.setStatus("draft");
        route.setDeletedFlag(0);
        when(processRepository.selectById(100L)).thenReturn(route);
        when(processRepository.selectList(Mockito.<Wrapper<ProcessEntity>>any())).thenReturn(List.of());
        when(productRepository.selectById(10L)).thenReturn(product(10L));
        ProcessRouteServiceImpl service = new ProcessRouteServiceImpl(
            productRepository,
            processRepository,
            mock(ProductBomRepository.class),
            mock(ProductBomRouteRepository.class),
            mock(OperationLogService.class),
            mock(ProcessRouteTemplateService.class),
            new ObjectMapper()
        );

        assertThatThrownBy(() -> service.freeze(100L, null))
            .isInstanceOf(BusinessException.class)
            .extracting("code")
            .isEqualTo(ErrorCodeConstants.VALIDATION_ERROR);
    }

    @Test
    void createFromTemplateUsesProductCodeAndCopiesTemplateOperations() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProcessRepository processRepository = mock(ProcessRepository.class);
        ProcessRouteTemplateService templateService = mock(ProcessRouteTemplateService.class);
        List<ProcessEntity> inserted = new ArrayList<>();
        AtomicLong idSequence = new AtomicLong(100L);
        when(productRepository.selectById(10L)).thenReturn(product(10L));
        when(processRepository.insert(Mockito.any(ProcessEntity.class))).thenAnswer(invocation -> {
            ProcessEntity entity = invocation.getArgument(0);
            entity.setProcessId(idSequence.getAndIncrement());
            inserted.add(entity);
            return 1;
        });
        when(processRepository.selectById(Mockito.anyLong())).thenAnswer(invocation -> inserted.stream()
            .filter(entity -> entity.getProcessId().equals(invocation.getArgument(0)))
            .findFirst()
            .orElse(null));
        when(processRepository.selectList(Mockito.<Wrapper<ProcessEntity>>any())).thenAnswer(invocation -> inserted.stream()
            .filter(entity -> "operation".equals(entity.getProcessType()))
            .toList());
        when(templateService.getPublishedTemplate("ROUTE-STD-INJECTION", "V1")).thenReturn(ProcessRouteTemplateVO.builder()
            .routeTemplateCode("ROUTE-STD-INJECTION")
            .routeTemplateName("Standard injection route")
            .versionNo("V1")
            .status("published")
            .defaultTemplate(true)
            .priority(100)
            .operations(List.of(
                ProcessRouteTemplateOperationVO.builder()
                    .operationCode("PROC_INJECTION")
                    .operationCraftCode("1010")
                    .sequenceNo(10)
                    .processName("Injection")
                    .qualityRequirement("No burrs")
                    .processParamJson("{\"temperature\":82}")
                    .build(),
                ProcessRouteTemplateOperationVO.builder()
                    .operationCode("PROC_PACKING")
                    .operationCraftCode("4030")
                    .sequenceNo(20)
                    .processName("Packing")
                    .qualityRequirement("No missing labels")
                    .processParamJson("{}")
                    .build()
            ))
            .build());
        ProcessRouteServiceImpl service = new ProcessRouteServiceImpl(
            productRepository,
            processRepository,
            mock(ProductBomRepository.class),
            mock(ProductBomRouteRepository.class),
            mock(OperationLogService.class),
            templateService,
            new ObjectMapper()
        );

        ProcessRouteSaveDTO dto = new ProcessRouteSaveDTO();
        dto.setProcessName("Injection route");
        dto.setVersionNo("V1");
        dto.setRouteTemplateCode("ROUTE-STD-INJECTION");
        dto.setRouteTemplateVersion("V1");
        dto.setCopyTemplateOperations(true);

        ProcessRouteVO result = service.create(10L, dto, null);

        assertThat(result.getProcessCode()).isEqualTo("PRD-1-ROUTE-E0297026");
        assertThat(result.getRouteTemplateCode()).isEqualTo("ROUTE-STD-INJECTION");
        assertThat(result.getRouteTemplateVersion()).isEqualTo("V1");
        assertThat(result.getOperations()).hasSize(2);
        assertThat(result.getOperations()).extracting("operationCode").containsExactly("PROC_INJECTION", "PROC_PACKING");
        assertThat(inserted).extracting(ProcessEntity::getProcessCode)
            .contains("PRD-1-ROUTE-E0297026-OP-010-PROC_INJECTION");
    }

    @Test
    void createModelVariantRouteAddsPhoneModelToNameAndLinePlaceholderToCode() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProcessRepository processRepository = mock(ProcessRepository.class);
        List<ProcessEntity> inserted = new ArrayList<>();
        AtomicLong idSequence = new AtomicLong(100L);
        Product product = product(10L, "PRD-超队30IP-0002");
        product.setProductType("model_variant");
        product.setModel("iphone 18");
        product.setPhoneModelCode("1801");
        product.setColorCode("02");
        when(productRepository.selectById(10L)).thenReturn(product);
        when(processRepository.insert(Mockito.any(ProcessEntity.class))).thenAnswer(invocation -> {
            ProcessEntity entity = invocation.getArgument(0);
            entity.setProcessId(idSequence.getAndIncrement());
            inserted.add(entity);
            return 1;
        });
        when(processRepository.selectById(Mockito.anyLong())).thenAnswer(invocation -> inserted.stream()
            .filter(entity -> entity.getProcessId().equals(invocation.getArgument(0)))
            .findFirst()
            .orElse(null));
        when(processRepository.selectList(Mockito.<Wrapper<ProcessEntity>>any())).thenAnswer(invocation -> inserted.stream()
            .filter(entity -> "operation".equals(entity.getProcessType()))
            .toList());
        ProcessRouteServiceImpl service = new ProcessRouteServiceImpl(
            productRepository,
            processRepository,
            mock(ProductBomRepository.class),
            mock(ProductBomRouteRepository.class),
            mock(OperationLogService.class),
            mock(ProcessRouteTemplateService.class),
            new ObjectMapper()
        );

        ProcessRouteSaveDTO dto = routeDTO(operation(10, "{}"));
        dto.setProcessName("标准注塑组装路线");
        dto.setVersionNo("V1");
        ProcessRouteVO result = service.create(10L, dto, null);

        assertThat(result.getProcessCode()).isEqualTo("PRD-30IP-00-431B17F7");
        assertThat(result.getProcessName()).isEqualTo("标准注塑组装路线 - iphone 18");
        assertThat(inserted).extracting(ProcessEntity::getProcessCode)
            .contains("PRD-30IP-00-431B17F7-OP-010-OP-10");
    }

    @Test
    void createWithOperationMasterUsesMasterSnapshotInsteadOfTypedName() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProcessRepository processRepository = mock(ProcessRepository.class);
        List<ProcessEntity> inserted = new ArrayList<>();
        AtomicLong idSequence = new AtomicLong(100L);
        ProcessEntity master = new ProcessEntity();
        master.setProcessId(900L);
        master.setProcessCode("PROC_INJECTION");
        master.setProcessName("Injection molding");
        master.setProcessType("operation_master");
        master.setProcessParamJson("{\"operationType\":\"process\",\"defaultProcessParamJson\":{\"temperature\":82}}");
        master.setStandardTimeMins(new BigDecimal("12.50"));
        master.setQualityRequirement("No burrs");
        master.setStatus("confirmed");
        master.setDeletedFlag(0);

        when(productRepository.selectById(10L)).thenReturn(product(10L));
        when(processRepository.selectById(900L)).thenReturn(master);
        when(processRepository.selectById(100L)).thenAnswer(invocation -> inserted.stream()
            .filter(entity -> entity.getProcessId().equals(invocation.getArgument(0)))
            .findFirst()
            .orElse(null));
        when(processRepository.insert(Mockito.any(ProcessEntity.class))).thenAnswer(invocation -> {
            ProcessEntity entity = invocation.getArgument(0);
            entity.setProcessId(idSequence.getAndIncrement());
            inserted.add(entity);
            return 1;
        });
        when(processRepository.selectList(Mockito.<Wrapper<ProcessEntity>>any())).thenAnswer(invocation -> inserted.stream()
            .filter(entity -> "operation".equals(entity.getProcessType()))
            .toList());
        ProcessRouteServiceImpl service = new ProcessRouteServiceImpl(
            productRepository,
            processRepository,
            mock(ProductBomRepository.class),
            mock(ProductBomRouteRepository.class),
            mock(OperationLogService.class),
            mock(ProcessRouteTemplateService.class),
            new ObjectMapper()
        );

        ProcessOperationDTO operation = operation(10, "{}");
        operation.setOperationMasterProcessId(900L);
        operation.setProcessName("Manual injection");
        operation.setOperationCode("manual-injection");
        operation.setOperationCraftCode("1030");
        operation.setQualityRequirement("");
        ProcessRouteVO result = service.create(10L, routeDTO(operation), null);

        assertThat(result.getOperations()).hasSize(1);
        assertThat(result.getOperations().get(0).getOperationMasterProcessId()).isEqualTo(900L);
        assertThat(result.getOperations().get(0).getOperationCode()).isEqualTo("MANUAL-INJECTION");
        assertThat(result.getOperations().get(0).getOperationCraftCode()).isEqualTo("1030");
        assertThat(result.getOperations().get(0).getProcessName()).isEqualTo("Manual injection");
        assertThat(result.getOperations().get(0).getQualityRequirement()).isEqualTo("No burrs");
    }

    @Test
    void createProductLineRouteAllowsManualOperationNameAndCodeWithoutMaster() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProcessRepository processRepository = mock(ProcessRepository.class);
        List<ProcessEntity> inserted = new ArrayList<>();
        AtomicLong idSequence = new AtomicLong(100L);

        Product product = product(20L, "FA");
        product.setProductType("product_line");
        product.setProductSpecificCode("FA");
        when(productRepository.selectById(20L)).thenReturn(product);
        when(processRepository.selectById(Mockito.anyLong())).thenAnswer(invocation -> inserted.stream()
            .filter(entity -> entity.getProcessId().equals(invocation.getArgument(0)))
            .findFirst()
            .orElse(null));
        when(processRepository.insert(Mockito.any(ProcessEntity.class))).thenAnswer(invocation -> {
            ProcessEntity entity = invocation.getArgument(0);
            entity.setProcessId(idSequence.getAndIncrement());
            inserted.add(entity);
            return 1;
        });
        when(processRepository.selectList(Mockito.<Wrapper<ProcessEntity>>any())).thenAnswer(invocation -> inserted.stream()
            .filter(entity -> "operation".equals(entity.getProcessType()))
            .toList());
        ProcessRouteServiceImpl service = new ProcessRouteServiceImpl(
            productRepository,
            processRepository,
            mock(ProductBomRepository.class),
            mock(ProductBomRouteRepository.class),
            mock(OperationLogService.class),
            mock(ProcessRouteTemplateService.class),
            new ObjectMapper()
        );

        ProcessOperationDTO operation = operation(10, "{}");
        operation.setOperationMasterProcessId(null);
        operation.setOperationSource("manual_snapshot");
        operation.setProcessName("手工注塑成型");
        operation.setOperationCode("manual-injection");
        operation.setOperationCraftCode("1010");

        ProcessRouteVO result = service.create(20L, routeDTO(operation), null);

        assertThat(result.getOperations()).hasSize(1);
        assertThat(result.getOperations().get(0).getOperationMasterProcessId()).isNull();
        assertThat(result.getOperations().get(0).getProcessName()).isEqualTo("手工注塑成型");
        assertThat(result.getOperations().get(0).getOperationCode()).isEqualTo("MANUAL-INJECTION");
        assertThat(result.getOperations().get(0).getOperationCraftCode()).isEqualTo("1010");
        assertThat(result.getOperations().get(0).getBusinessOperationCode()).isEqualTo("NFA1010");
        assertThat(result.getOperations().get(0).getCodeGenerationContext()).isEqualTo("product_line_route");
    }

    @Test
    void createSkuRouteAppendsPhoneModelAndColorToManualOperationCode() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProcessRepository processRepository = mock(ProcessRepository.class);
        List<ProcessEntity> inserted = new ArrayList<>();
        AtomicLong idSequence = new AtomicLong(100L);

        Product product = product(20L, "HD");
        product.setProductType("sku");
        product.setProductSpecificCode("HD");
        product.setPhoneModelCode("1801");
        product.setColorCode("02");
        when(productRepository.selectById(20L)).thenReturn(product);
        when(processRepository.selectById(Mockito.anyLong())).thenAnswer(invocation -> inserted.stream()
            .filter(entity -> entity.getProcessId().equals(invocation.getArgument(0)))
            .findFirst()
            .orElse(null));
        when(processRepository.insert(Mockito.any(ProcessEntity.class))).thenAnswer(invocation -> {
            ProcessEntity entity = invocation.getArgument(0);
            entity.setProcessId(idSequence.getAndIncrement());
            inserted.add(entity);
            return 1;
        });
        when(processRepository.selectList(Mockito.<Wrapper<ProcessEntity>>any())).thenAnswer(invocation -> inserted.stream()
            .filter(entity -> "operation".equals(entity.getProcessType()))
            .toList());
        ProcessRouteServiceImpl service = new ProcessRouteServiceImpl(
            productRepository,
            processRepository,
            mock(ProductBomRepository.class),
            mock(ProductBomRouteRepository.class),
            mock(OperationLogService.class),
            mock(ProcessRouteTemplateService.class),
            new ObjectMapper()
        );

        ProcessOperationDTO operation = operation(10, "{}");
        operation.setOperationMasterProcessId(null);
        operation.setOperationSource("manual_snapshot");
        operation.setProcessName("手工成品包装");
        operation.setOperationCraftCode("4030");

        ProcessRouteVO result = service.create(20L, routeDTO(operation), null);

        assertThat(result.getOperations().get(0).getBusinessOperationCode()).isEqualTo("NHD4030180102");
        assertThat(result.getOperations().get(0).getGeneratedFinishedProductCode()).isEqualTo("NHD4030180102");
        assertThat(result.getOperations().get(0).getPhoneModelCode()).isEqualTo("1801");
        assertThat(result.getOperations().get(0).getColorCode()).isEqualTo("02");
        assertThat(result.getOperations().get(0).getCodeGenerationContext()).isEqualTo("sku_route");
    }

    @Test
    void createLeavesProductLineBusinessOperationCodePendingWithoutModelAndColor() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProcessRepository processRepository = mock(ProcessRepository.class);
        List<ProcessEntity> inserted = new ArrayList<>();
        AtomicLong idSequence = new AtomicLong(100L);
        ProcessEntity master = operationMaster(900L, "PROC_INJECTION", "Injection molding", "{\"operationCraftCode\":\"1020\"}");

        Product product = product(20L, "FA");
        product.setProductType("product_line");
        product.setProductSpecificCode("FA");
        product.setColor("[\"02 Negro\",\"03 Humo\",\"04 Blanco\"]");
        when(productRepository.selectById(20L)).thenReturn(product);
        when(processRepository.selectById(900L)).thenReturn(master);
        when(processRepository.selectById(100L)).thenAnswer(invocation -> inserted.stream()
            .filter(entity -> entity.getProcessId().equals(invocation.getArgument(0)))
            .findFirst()
            .orElse(null));
        when(processRepository.insert(Mockito.any(ProcessEntity.class))).thenAnswer(invocation -> {
            ProcessEntity entity = invocation.getArgument(0);
            entity.setProcessId(idSequence.getAndIncrement());
            inserted.add(entity);
            return 1;
        });
        when(processRepository.selectList(Mockito.<Wrapper<ProcessEntity>>any())).thenAnswer(invocation -> inserted.stream()
            .filter(entity -> "operation".equals(entity.getProcessType()))
            .toList());
        ProcessRouteServiceImpl service = new ProcessRouteServiceImpl(
            productRepository,
            processRepository,
            mock(ProductBomRepository.class),
            mock(ProductBomRouteRepository.class),
            mock(OperationLogService.class),
            mock(ProcessRouteTemplateService.class),
            new ObjectMapper()
        );

        ProcessOperationDTO operation = operation(10, "{}");
        operation.setOperationMasterProcessId(900L);
        operation.setOperationCraftCode("1020");

        ProcessRouteVO result = service.create(20L, routeDTO(operation), null);

        assertThat(result.getOperations().get(0).getOperationCraftCode()).isEqualTo("1020");
        assertThat(result.getOperations().get(0).getBusinessOperationCode()).isEqualTo("NFA1020");
        assertThat(result.getOperations().get(0).getGeneratedFinishedProductCode()).isNull();
        assertThat(result.getOperations().get(0).getProductSpecificCode()).isEqualTo("FA");
        assertThat(result.getOperations().get(0).getPhoneModelCode()).isNull();
        assertThat(result.getOperations().get(0).getColorCode()).isNull();
        assertThat(result.getOperations().get(0).getCodeGenerationContext()).isEqualTo("product_line_route");
        assertThat(result.getOperations().get(0).getBusinessOperationCodeManualFlag()).isFalse();
    }

    @Test
    void createDoesNotFallbackProjectCodeToProductSpecificCode() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProcessRepository processRepository = mock(ProcessRepository.class);
        List<ProcessEntity> inserted = new ArrayList<>();
        AtomicLong idSequence = new AtomicLong(100L);
        ProcessEntity master = operationMaster(900L, "PROC_INJECTION", "Injection molding", "{\"operationCraftCode\":\"1020\"}");

        Product product = product(20L, "PRD-SPER-0005");
        product.setProductType("product_line");
        when(productRepository.selectById(20L)).thenReturn(product);
        when(processRepository.selectById(900L)).thenReturn(master);
        when(processRepository.selectById(100L)).thenAnswer(invocation -> inserted.stream()
            .filter(entity -> entity.getProcessId().equals(invocation.getArgument(0)))
            .findFirst()
            .orElse(null));
        when(processRepository.insert(Mockito.any(ProcessEntity.class))).thenAnswer(invocation -> {
            ProcessEntity entity = invocation.getArgument(0);
            entity.setProcessId(idSequence.getAndIncrement());
            inserted.add(entity);
            return 1;
        });
        when(processRepository.selectList(Mockito.<Wrapper<ProcessEntity>>any())).thenAnswer(invocation -> inserted.stream()
            .filter(entity -> "operation".equals(entity.getProcessType()))
            .toList());
        ProcessRouteServiceImpl service = new ProcessRouteServiceImpl(
            productRepository,
            processRepository,
            mock(ProductBomRepository.class),
            mock(ProductBomRouteRepository.class),
            mock(OperationLogService.class),
            mock(ProcessRouteTemplateService.class),
            new ObjectMapper()
        );

        ProcessOperationDTO operation = operation(10, "{}");
        operation.setOperationMasterProcessId(900L);
        operation.setOperationCraftCode("1020");

        ProcessRouteVO result = service.create(20L, routeDTO(operation), null);

        assertThat(result.getOperations().get(0).getProductSpecificCode()).isNull();
        assertThat(result.getOperations().get(0).getBusinessOperationCode()).isNull();
        assertThat(result.getOperations().get(0).getProcessParamJson()).doesNotContain("PRDSPER0005");
    }

    @Test
    void createGeneratesModelVariantFinishedProductCodeWithPhoneAndColor() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProcessRepository processRepository = mock(ProcessRepository.class);
        List<ProcessEntity> inserted = new ArrayList<>();
        AtomicLong idSequence = new AtomicLong(100L);
        ProcessEntity master = operationMaster(900L, "PROC_PACKING", "Packing", "{\"operationCraftCode\":\"4030\"}");

        Product product = product(20L, "FA");
        product.setProductType("model_variant");
        product.setProductSpecificCode("FA");
        product.setModel("iPhone 1291");
        product.setPhoneModelCode("1291");
        product.setColorCode("01");
        when(productRepository.selectById(20L)).thenReturn(product);
        when(processRepository.selectById(900L)).thenReturn(master);
        when(processRepository.selectById(100L)).thenAnswer(invocation -> inserted.stream()
            .filter(entity -> entity.getProcessId().equals(invocation.getArgument(0)))
            .findFirst()
            .orElse(null));
        when(processRepository.insert(Mockito.any(ProcessEntity.class))).thenAnswer(invocation -> {
            ProcessEntity entity = invocation.getArgument(0);
            entity.setProcessId(idSequence.getAndIncrement());
            inserted.add(entity);
            return 1;
        });
        when(processRepository.selectList(Mockito.<Wrapper<ProcessEntity>>any())).thenAnswer(invocation -> inserted.stream()
            .filter(entity -> "operation".equals(entity.getProcessType()))
            .toList());
        ProcessRouteServiceImpl service = new ProcessRouteServiceImpl(
            productRepository,
            processRepository,
            mock(ProductBomRepository.class),
            mock(ProductBomRouteRepository.class),
            mock(OperationLogService.class),
            mock(ProcessRouteTemplateService.class),
            new ObjectMapper()
        );

        ProcessOperationDTO operation = operation(10, "{}");
        operation.setOperationMasterProcessId(900L);
        operation.setOperationCraftCode("4030");

        ProcessRouteVO result = service.create(20L, routeDTO(operation), null);

        assertThat(result.getOperations().get(0).getBusinessOperationCode()).isEqualTo("NFA40301291");
        assertThat(result.getOperations().get(0).getGeneratedFinishedProductCode()).isEqualTo("NFA40301291");
        assertThat(result.getOperations().get(0).getPhoneModelCode()).isEqualTo("1291");
        assertThat(result.getOperations().get(0).getColorCode()).isNull();
        assertThat(result.getOperations().get(0).getCodeGenerationContext()).isEqualTo("model_variant_route");
    }

    @Test
    void createAllowsRepeatedSystemOperationCodesWhenFormalBusinessCodesArePending() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProcessRepository processRepository = mock(ProcessRepository.class);
        List<ProcessEntity> inserted = new ArrayList<>();
        AtomicLong idSequence = new AtomicLong(100L);
        ProcessEntity master = operationMaster(900L, "PROC_INJECTION", "Injection molding", "{\"operationCraftCode\":\"1010\"}");

        Product product = product(20L, "BA");
        product.setProductType("product_line");
        product.setProductSpecificCode("BA");
        when(productRepository.selectById(20L)).thenReturn(product);
        when(processRepository.selectById(900L)).thenReturn(master);
        when(processRepository.selectById(100L)).thenAnswer(invocation -> inserted.stream()
            .filter(entity -> entity.getProcessId().equals(invocation.getArgument(0)))
            .findFirst()
            .orElse(null));
        when(processRepository.insert(Mockito.any(ProcessEntity.class))).thenAnswer(invocation -> {
            ProcessEntity entity = invocation.getArgument(0);
            entity.setProcessId(idSequence.getAndIncrement());
            inserted.add(entity);
            return 1;
        });
        when(processRepository.selectList(Mockito.<Wrapper<ProcessEntity>>any())).thenAnswer(invocation -> inserted.stream()
            .filter(entity -> "operation".equals(entity.getProcessType()))
            .toList());
        ProcessRouteServiceImpl service = new ProcessRouteServiceImpl(
            productRepository,
            processRepository,
            mock(ProductBomRepository.class),
            mock(ProductBomRouteRepository.class),
            mock(OperationLogService.class),
            mock(ProcessRouteTemplateService.class),
            new ObjectMapper()
        );

        ProcessOperationDTO first = operation(10, "{}");
        first.setOperationMasterProcessId(900L);
        first.setOperationCraftCode("1010");
        first.setMaterialStatusCode("10");
        ProcessOperationDTO second = operation(20, "{}");
        second.setOperationMasterProcessId(900L);
        second.setOperationCraftCode("1020");
        second.setMaterialStatusCode("20");

        ProcessRouteVO result = service.create(20L, routeDTO(first, second), null);

        assertThat(result.getOperations()).extracting("operationCode").containsExactly("PROC_INJECTION", "PROC_INJECTION");
        assertThat(result.getOperations()).extracting("businessOperationCode").containsExactly("NBA1010", "NBA1020");
        assertThat(inserted).extracting(ProcessEntity::getProcessCode)
            .contains("BA-CUSTOM-A-OP-010-PROC_INJECTION", "BA-CUSTOM-A-OP-020-PROC_INJECTION");
    }

    @Test
    void createPersistsManualBusinessOperationCode() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProcessRepository processRepository = mock(ProcessRepository.class);
        List<ProcessEntity> inserted = new ArrayList<>();
        AtomicLong idSequence = new AtomicLong(100L);
        ProcessEntity master = operationMaster(900L, "PROC_INJECTION", "Injection molding", "{\"operationCraftCode\":\"10\"}");

        Product product = product(20L, "BA");
        product.setProductType("sku");
        product.setProductSpecificCode("BA");
        product.setPhoneModelCode("1291");
        product.setColorCode("01");
        when(productRepository.selectById(20L)).thenReturn(product);
        when(processRepository.selectById(900L)).thenReturn(master);
        when(processRepository.selectById(100L)).thenAnswer(invocation -> inserted.stream()
            .filter(entity -> entity.getProcessId().equals(invocation.getArgument(0)))
            .findFirst()
            .orElse(null));
        when(processRepository.insert(Mockito.any(ProcessEntity.class))).thenAnswer(invocation -> {
            ProcessEntity entity = invocation.getArgument(0);
            entity.setProcessId(idSequence.getAndIncrement());
            inserted.add(entity);
            return 1;
        });
        when(processRepository.selectList(Mockito.<Wrapper<ProcessEntity>>any())).thenAnswer(invocation -> inserted.stream()
            .filter(entity -> "operation".equals(entity.getProcessType()))
            .toList());
        ProcessRouteServiceImpl service = new ProcessRouteServiceImpl(
            productRepository,
            processRepository,
            mock(ProductBomRepository.class),
            mock(ProductBomRouteRepository.class),
            mock(OperationLogService.class),
            mock(ProcessRouteTemplateService.class),
            new ObjectMapper()
        );

        ProcessOperationDTO operation = operation(10, "{}");
        operation.setOperationMasterProcessId(900L);
        operation.setOperationCraftCode("10");
        operation.setMaterialStatusCode("20");
        operation.setBusinessOperationCode("nba10a1");
        operation.setBusinessOperationCodeManualFlag(true);

        ProcessRouteVO result = service.create(20L, routeDTO(operation), null);

        assertThat(result.getOperations().get(0).getBusinessOperationCode()).isEqualTo("NBA10A1129101");
        assertThat(result.getOperations().get(0).getBusinessOperationCodeManualFlag()).isTrue();
        assertThat(result.getOperations().get(0).getMaterialStatusCode()).isEqualTo("20");
        assertThat(result.getOperations().get(0).getFinishedProductFlag()).isFalse();
    }

    @Test
    void concreteRouteRejectsMissingPhoneModelOrColorCodeBeforeInsert() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProcessRepository processRepository = mock(ProcessRepository.class);
        Product product = product(20L, "FA");
        product.setProductType("model_variant");
        when(productRepository.selectById(20L)).thenReturn(product);
        ProcessRouteServiceImpl service = new ProcessRouteServiceImpl(
            productRepository,
            processRepository,
            mock(ProductBomRepository.class),
            mock(ProductBomRouteRepository.class),
            mock(OperationLogService.class),
            mock(ProcessRouteTemplateService.class),
            new ObjectMapper()
        );

        ProcessOperationDTO operation = operation(10, "{}");
        operation.setOperationCraftCode("1010");

        assertThatThrownBy(() -> service.create(20L, routeDTO(operation), null))
            .isInstanceOf(BusinessException.class)
            .hasMessageContaining("4 位手机型号编码")
            .extracting("code")
            .isEqualTo(ErrorCodeConstants.VALIDATION_ERROR);
        Mockito.verify(processRepository, Mockito.never()).insert(Mockito.any(ProcessEntity.class));
    }

    @Test
    void createRejectsFinishedProductAsMaterialStatusCode() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProcessRepository processRepository = mock(ProcessRepository.class);
        ProcessEntity master = operationMaster(900L, "PROC_INJECTION", "Injection molding", "{\"operationCraftCode\":\"10\"}");
        when(productRepository.selectById(20L)).thenReturn(product(20L, "BA"));
        when(processRepository.selectById(900L)).thenReturn(master);
        ProcessRouteServiceImpl service = new ProcessRouteServiceImpl(
            productRepository,
            processRepository,
            mock(ProductBomRepository.class),
            mock(ProductBomRouteRepository.class),
            mock(OperationLogService.class),
            mock(ProcessRouteTemplateService.class),
            new ObjectMapper()
        );

        ProcessOperationDTO operation = operation(10, "{}");
        operation.setOperationMasterProcessId(900L);
        operation.setOperationCraftCode("10");
        operation.setMaterialStatusCode("40");

        assertThatThrownBy(() -> service.create(20L, routeDTO(operation), null))
            .isInstanceOf(BusinessException.class)
            .extracting("code")
            .isEqualTo(ErrorCodeConstants.VALIDATION_ERROR);
    }

    @Test
    void createRejectsUnavailableOperationMaster() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProcessRepository processRepository = mock(ProcessRepository.class);
        ProcessEntity archivedMaster = new ProcessEntity();
        archivedMaster.setProcessId(900L);
        archivedMaster.setProcessType("operation_master");
        archivedMaster.setStatus("archived");
        archivedMaster.setDeletedFlag(0);
        when(productRepository.selectById(10L)).thenReturn(product(10L));
        when(processRepository.selectById(900L)).thenReturn(archivedMaster);
        ProcessRouteServiceImpl service = new ProcessRouteServiceImpl(
            productRepository,
            processRepository,
            mock(ProductBomRepository.class),
            mock(ProductBomRouteRepository.class),
            mock(OperationLogService.class),
            mock(ProcessRouteTemplateService.class),
            new ObjectMapper()
        );

        ProcessOperationDTO operation = operation(10, "{}");
        operation.setOperationMasterProcessId(900L);

        assertThatThrownBy(() -> service.create(10L, routeDTO(operation), null))
            .isInstanceOf(BusinessException.class)
            .extracting("code")
            .isEqualTo(ErrorCodeConstants.VALIDATION_ERROR);
    }

    @Test
    void deleteVersionRejectsActiveBomReference() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProcessRepository processRepository = mock(ProcessRepository.class);
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProductBomRouteRepository routeRepository = mock(ProductBomRouteRepository.class);
        ProcessEntity route = new ProcessEntity();
        route.setProcessId(100L);
        route.setProductId(10L);
        route.setProcessType("routing");
        route.setStatus("draft");
        route.setDeletedFlag(0);
        when(productRepository.selectById(10L)).thenReturn(product(10L));
        when(processRepository.selectById(100L)).thenReturn(route);
        ProcessRouteServiceImpl service = new ProcessRouteServiceImpl(
            productRepository,
            processRepository,
            bomRepository,
            routeRepository,
            mock(OperationLogService.class),
            mock(ProcessRouteTemplateService.class),
            new ObjectMapper()
        );
        when(routeRepository.selectList(Mockito.<Wrapper<com.yuewei.plm.module.bom.entity.ProductBomRoute>>any()))
            .thenAnswer(invocation -> {
                com.yuewei.plm.module.bom.entity.ProductBomRoute ref = new com.yuewei.plm.module.bom.entity.ProductBomRoute();
                ref.setProductBomId(200L);
                ref.setProcessId(100L);
                ref.setDeletedFlag(0);
                return List.of(ref);
            });
        when(bomRepository.selectList(Mockito.<Wrapper<com.yuewei.plm.module.bom.entity.ProductBom>>any()))
            .thenAnswer(invocation -> {
                com.yuewei.plm.module.bom.entity.ProductBom bom = new com.yuewei.plm.module.bom.entity.ProductBom();
                bom.setProductBomId(200L);
                bom.setDeletedFlag(0);
                return List.of(bom);
            });

        assertThatThrownBy(() -> service.deleteVersion(100L, null))
            .isInstanceOf(BusinessException.class)
            .extracting("code")
            .isEqualTo(ErrorCodeConstants.VALIDATION_ERROR);
    }

    private ProcessRouteSaveDTO routeDTO(ProcessOperationDTO... operations) {
        ProcessRouteSaveDTO dto = new ProcessRouteSaveDTO();
        dto.setProcessName("超队3.0 样品工艺路线");
        dto.setVersionNo("A");
        dto.setOperations(List.of(operations));
        return dto;
    }

    private ProcessOperationDTO operation(Integer sequenceNo, String paramJson) {
        ProcessOperationDTO dto = new ProcessOperationDTO();
        dto.setSequenceNo(sequenceNo);
        dto.setProcessName("注塑成型");
        dto.setOperationCraftCode("1010");
        dto.setProcessParamJson(paramJson);
        dto.setStandardTimeMins(new BigDecimal("15"));
        dto.setQualityRequirement("外观无缩水、无明显披锋");
        return dto;
    }

    private Product product(Long productId, String productCode) {
        Product product = new Product();
        product.setProductId(productId);
        product.setProductCode(productCode);
        product.setProductName("Test product");
        product.setDeletedFlag(0);
        return product;
    }

    private Product product(Long productId) {
        Product product = new Product();
        product.setProductId(productId);
        product.setProductCode("PRD-1");
        product.setProductName("超队3.0");
        product.setDeletedFlag(0);
        return product;
    }

    private ProcessEntity operationMaster(Long processId, String processCode, String processName, String metadataJson) {
        ProcessEntity master = new ProcessEntity();
        master.setProcessId(processId);
        master.setProcessCode(processCode);
        master.setProcessName(processName);
        master.setProcessType("operation_master");
        master.setProcessParamJson(metadataJson);
        master.setStandardTimeMins(new BigDecimal("12.50"));
        master.setQualityRequirement("No burrs");
        master.setStatus("confirmed");
        master.setDeletedFlag(0);
        return master;
    }
}
