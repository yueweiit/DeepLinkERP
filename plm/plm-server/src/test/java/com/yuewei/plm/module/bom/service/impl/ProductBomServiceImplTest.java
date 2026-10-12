package com.yuewei.plm.module.bom.service.impl;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.module.bom.dto.ProductBomCreateDTO;
import com.yuewei.plm.module.bom.dto.ProductBomItemDTO;
import com.yuewei.plm.module.bom.entity.ProductBom;
import com.yuewei.plm.module.bom.entity.ProductBomItem;
import com.yuewei.plm.module.bom.entity.ProductBomRoute;
import com.yuewei.plm.module.bom.entity.ProductBomRouteFormalSelection;
import com.yuewei.plm.module.bom.repository.ProductBomCostSnapshotRepository;
import com.yuewei.plm.module.bom.repository.ProductBomItemRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteColorRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteFormalSelectionRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteRepository;
import com.yuewei.plm.module.bom.vo.ProductBomItemVO;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.process.entity.ProcessEntity;
import com.yuewei.plm.module.process.repository.ProcessRepository;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import java.math.BigDecimal;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;

class ProductBomServiceImplTest {
    private final com.yuewei.plm.module.pilotdelivery.BomReleaseDeliveryService releaseDelivery=mock(com.yuewei.plm.module.pilotdelivery.BomReleaseDeliveryService.class);
    private final com.yuewei.plm.module.pilot.PilotAccessService amountAccess=mock(com.yuewei.plm.module.pilot.PilotAccessService.class);
    @org.junit.jupiter.api.BeforeEach void moneyPermission(){when(amountAccess.hasPermission("finance:write")).thenReturn(true);}
    private ProductBomServiceImpl service(ProductRepository products,ProductBomRepository boms,ProductBomItemRepository items,ProductBomRouteRepository routes,ProductBomRouteColorRepository colors,ProductBomCostSnapshotRepository costs,ProductBomRouteFormalSelectionRepository selections,ProcessRepository processes,OperationLogService logs){return new ProductBomServiceImpl(products,boms,items,routes,colors,costs,selections,processes,logs,releaseDelivery,amountAccess,mock(org.springframework.jdbc.core.JdbcTemplate.class));}

    @Test
    void createBomAndAddItemWritesDraftData() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProductBomItemRepository itemRepository = mock(ProductBomItemRepository.class);
        ProductBomRouteRepository routeRepository = mock(ProductBomRouteRepository.class);
        ProductBomRouteFormalSelectionRepository formalSelectionRepository = mock(ProductBomRouteFormalSelectionRepository.class);
        ProcessRepository processRepository = mock(ProcessRepository.class);
        OperationLogService operationLogService = mock(OperationLogService.class);
        ProductBomServiceImpl service = service(
            productRepository, bomRepository, itemRepository, routeRepository,
            mock(ProductBomRouteColorRepository.class), mock(ProductBomCostSnapshotRepository.class),
            formalSelectionRepository, processRepository, operationLogService
        );
        Product product = product(10L);
        ProductBom bom = bom(100L, 10L, "draft");
        bom.setBomScope("candidate");
        ProductBomRoute createdRoute = route(300L, 100L, 10L, 66L);
        when(productRepository.selectById(10L)).thenReturn(product);
        when(processRepository.selectById(66L)).thenReturn(routeProcess(66L, 10L));
        when(bomRepository.insert(any(ProductBom.class))).thenAnswer(invocation -> {
            ProductBom inserted = invocation.getArgument(0);
            inserted.setProductBomId(100L);
            return 1;
        });
        when(routeRepository.insert(any(ProductBomRoute.class))).thenAnswer(invocation -> {
            ProductBomRoute inserted = invocation.getArgument(0);
            inserted.setProductBomRouteId(300L);
            return 1;
        });
        when(bomRepository.selectById(100L)).thenReturn(bom);
        when(routeRepository.selectList(Mockito.<Wrapper<ProductBomRoute>>any())).thenReturn(List.of(createdRoute));
        when(itemRepository.selectList(Mockito.<Wrapper<ProductBomItem>>any())).thenReturn(List.of());
        when(itemRepository.selectCount(Mockito.<Wrapper<ProductBomItem>>any())).thenReturn(0L);
        when(itemRepository.insert(any(ProductBomItem.class))).thenAnswer(invocation -> {
            ProductBomItem inserted = invocation.getArgument(0);
            inserted.setProductBomItemId(200L);
            return 1;
        });

        ProductBomCreateDTO createDTO = new ProductBomCreateDTO();
        createDTO.setBomName("超队3.0 样品BOM");
        createDTO.setBomType("ebom");
        createDTO.setVersionNo("A");
        createDTO.setProcessId(66L);
        var created = service.create(10L, createDTO, null);
        var withItem = service.addItem(100L, itemDTO(10), null);

        assertThat(created.getProductBomId()).isEqualTo(100L);
        assertThat(created.getBomScope()).isEqualTo("candidate");
        assertThat(created.getProcessId()).isEqualTo(66L);
        assertThat(withItem.getProductBomId()).isEqualTo(100L);
        ArgumentCaptor<ProductBom> bomCaptor = ArgumentCaptor.forClass(ProductBom.class);
        verify(bomRepository).insert(bomCaptor.capture());
        assertThat(bomCaptor.getValue().getBomScope()).isEqualTo("candidate");
        ArgumentCaptor<ProductBomRoute> routeCaptor = ArgumentCaptor.forClass(ProductBomRoute.class);
        verify(routeRepository).insert(routeCaptor.capture());
        assertThat(routeCaptor.getValue().getProductBomId()).isEqualTo(100L);
        assertThat(routeCaptor.getValue().getProductId()).isEqualTo(10L);
        assertThat(routeCaptor.getValue().getProcessId()).isEqualTo(66L);
        ArgumentCaptor<ProductBomItem> itemCaptor = ArgumentCaptor.forClass(ProductBomItem.class);
        verify(itemRepository).insert(itemCaptor.capture());
        assertThat(itemCaptor.getValue().getProductId()).isEqualTo(10L);
        assertThat(itemCaptor.getValue().getVersionNo()).isEqualTo("A");
        assertThat(itemCaptor.getValue().getUnit()).isEqualTo("kg");
        assertThat(itemCaptor.getValue().getSupplierCodeSnapshot()).isEqualTo("SUP-A");
        assertThat(itemCaptor.getValue().getSupplierNameSnapshot()).isEqualTo("东莞塑胶 A");
        assertThat(itemCaptor.getValue().getUnitCostSnapshot()).isEqualByComparingTo("3.50");
        assertThat(itemCaptor.getValue().getLineCostSnapshot()).isEqualByComparingTo("0.2800");
        assertThat(itemCaptor.getValue().getMaterialSource()).isEqualTo("inventory");
        assertThat(itemCaptor.getValue().getUnmatchedFlag()).isZero();
        verify(operationLogService, Mockito.atLeastOnce()).logSuccess(any());
    }

    @Test
    void addItemAllowsManualUnmatchedMaterialAndReturnsSnapshotFields() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProductBomItemRepository itemRepository = mock(ProductBomItemRepository.class);
        ProductBomRouteRepository routeRepository = mock(ProductBomRouteRepository.class);
        ProductBomRouteFormalSelectionRepository formalSelectionRepository = mock(ProductBomRouteFormalSelectionRepository.class);
        ProductBomServiceImpl service = service(
            productRepository, bomRepository, itemRepository, routeRepository,
            mock(ProductBomRouteColorRepository.class), mock(ProductBomCostSnapshotRepository.class),
            formalSelectionRepository, mock(ProcessRepository.class), mock(OperationLogService.class)
        );
        ProductBom bom = bom(100L, 10L, "draft");
        bom.setVersionNo("V1");
        when(bomRepository.selectById(100L)).thenReturn(bom);
        when(productRepository.selectById(10L)).thenReturn(product(10L));
        when(itemRepository.selectCount(Mockito.<Wrapper<ProductBomItem>>any())).thenReturn(0L);
        when(routeRepository.selectList(Mockito.<Wrapper<ProductBomRoute>>any())).thenReturn(List.of());
        when(formalSelectionRepository.selectList(Mockito.<Wrapper<ProductBomRouteFormalSelection>>any())).thenReturn(List.of());
        when(itemRepository.insert(any(ProductBomItem.class))).thenAnswer(invocation -> {
            ProductBomItem inserted = invocation.getArgument(0);
            inserted.setProductBomItemId(201L);
            return 1;
        });
        when(itemRepository.selectList(Mockito.<Wrapper<ProductBomItem>>any())).thenAnswer(invocation -> {
            ProductBomItem row = new ProductBomItem();
            row.setProductBomItemId(201L);
            row.setProductBomId(100L);
            row.setItemCode("INV-UNKNOWN-001");
            row.setItemName("人工 TPU");
            row.setLineNo(11);
            row.setQuantity(new BigDecimal("2"));
            row.setUnit("kg");
            row.setSupplierNameSnapshot("人工供应商");
            row.setUnitCostSnapshot(new BigDecimal("4.20"));
            row.setLineCostSnapshot(new BigDecimal("8.4000"));
            row.setMaterialSource("manual");
            row.setUnmatchedFlag(1);
            row.setStatus("draft");
            return List.of(row);
        });

        ProductBomItemDTO dto = itemDTO(11);
        dto.setItemCode("INV-UNKNOWN-001");
        dto.setItemName("人工 TPU");
        dto.setQuantity(new BigDecimal("2"));
        dto.setSupplierName("人工供应商");
        dto.setUnitCost(new BigDecimal("4.20"));
        dto.setMaterialSource("manual");
        dto.setUnmatchedFlag(1);

        var result = service.addItem(100L, dto, null);

        assertThat(result.getItems()).hasSize(1);
        ProductBomItemVO item = result.getItems().get(0);
        assertThat(item.getSupplierName()).isEqualTo("人工供应商");
        assertThat(item.getUnitCost()).isEqualByComparingTo("4.20");
        assertThat(item.getLineCost()).isEqualByComparingTo("8.4000");
        assertThat(item.getMaterialSource()).isEqualTo("manual");
        assertThat(item.getUnmatchedFlag()).isEqualTo(1);
    }

    @Test
    void frozenBomRejectsItemChangeAndRequiresANewVersion() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProductBomItemRepository itemRepository = mock(ProductBomItemRepository.class);
        ProductBomRouteRepository routeRepository = mock(ProductBomRouteRepository.class);
        ProductBomRouteFormalSelectionRepository formalSelectionRepository = mock(ProductBomRouteFormalSelectionRepository.class);
        ProductBomServiceImpl service = service(
            productRepository,
            bomRepository,
            itemRepository,
            routeRepository,
            mock(ProductBomRouteColorRepository.class),
            mock(ProductBomCostSnapshotRepository.class),
            formalSelectionRepository,
            mock(ProcessRepository.class),
            mock(OperationLogService.class)
        );
        ProductBom bom = bom(100L, 10L, "frozen");
        bom.setVersionNo("V1");
        when(bomRepository.selectById(100L)).thenReturn(bom);
        when(productRepository.selectById(10L)).thenReturn(product(10L));
        when(itemRepository.selectCount(Mockito.<Wrapper<ProductBomItem>>any())).thenReturn(0L);
        when(routeRepository.selectList(Mockito.<Wrapper<ProductBomRoute>>any())).thenReturn(List.of());
        when(formalSelectionRepository.selectList(Mockito.<Wrapper<ProductBomRouteFormalSelection>>any())).thenReturn(List.of());
        when(itemRepository.insert(any(ProductBomItem.class))).thenAnswer(invocation -> {
            ProductBomItem inserted = invocation.getArgument(0);
            inserted.setProductBomItemId(202L);
            return 1;
        });
        when(itemRepository.selectList(Mockito.<Wrapper<ProductBomItem>>any())).thenAnswer(invocation -> {
            ProductBomItem row = new ProductBomItem();
            row.setProductBomItemId(202L);
            row.setProductBomId(100L);
            row.setItemCode("INV-FROZEN-001");
            row.setItemName("冻结 TPU");
            row.setLineNo(12);
            row.setQuantity(new BigDecimal("1"));
            row.setUnit("kg");
            row.setSupplierNameSnapshot("冻结供应商");
            row.setUnitCostSnapshot(new BigDecimal("5.00"));
            row.setLineCostSnapshot(new BigDecimal("5.0000"));
            row.setMaterialSource("manual");
            row.setUnmatchedFlag(1);
            row.setStatus("draft");
            return List.of(row);
        });

        ProductBomItemDTO dto = itemDTO(12);
        dto.setItemCode("INV-FROZEN-001");
        dto.setItemName("冻结 TPU");
        dto.setQuantity(new BigDecimal("1"));
        dto.setSupplierName("冻结供应商");
        dto.setUnitCost(new BigDecimal("5.00"));
        dto.setMaterialSource("manual");
        dto.setUnmatchedFlag(1);

        assertThatThrownBy(() -> service.addItem(100L, dto, null))
            .isInstanceOf(BusinessException.class).hasMessageContaining("复制新版本");
        verify(itemRepository,Mockito.never()).insert(any(ProductBomItem.class));
    }

    @Test
    void duplicateLineNoRejectsAddItem() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProductBomItemRepository itemRepository = mock(ProductBomItemRepository.class);
        ProductBomServiceImpl service = service(
            productRepository,
            bomRepository,
            itemRepository,
            mock(ProductBomRouteRepository.class),
            mock(ProductBomRouteColorRepository.class),
            mock(ProductBomCostSnapshotRepository.class),
            mock(ProductBomRouteFormalSelectionRepository.class),
            mock(ProcessRepository.class),
            mock(OperationLogService.class)
        );
        when(bomRepository.selectById(100L)).thenReturn(bom(100L, 10L, "draft"));
        when(productRepository.selectById(10L)).thenReturn(product(10L));
        when(itemRepository.selectCount(Mockito.<Wrapper<ProductBomItem>>any())).thenReturn(1L);

        assertThatThrownBy(() -> service.addItem(100L, itemDTO(10), null))
            .isInstanceOf(BusinessException.class)
            .extracting("code")
            .isEqualTo(ErrorCodeConstants.CODE_CONFLICT);
    }

    @Test
    void createBomRejectsRouteOutsideProject() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProcessRepository processRepository = mock(ProcessRepository.class);
        ProductBomServiceImpl service = service(
            productRepository,
            bomRepository,
            mock(ProductBomItemRepository.class),
            mock(ProductBomRouteRepository.class),
            mock(ProductBomRouteColorRepository.class),
            mock(ProductBomCostSnapshotRepository.class),
            mock(ProductBomRouteFormalSelectionRepository.class),
            processRepository,
            mock(OperationLogService.class)
        );
        when(productRepository.selectById(10L)).thenReturn(product(10L));
        when(processRepository.selectById(66L)).thenReturn(routeProcess(66L, 99L));
        ProductBomCreateDTO dto = new ProductBomCreateDTO();
        dto.setBomName("候选 BOM");
        dto.setBomType("mbom");
        dto.setVersionNo("V1");
        dto.setProcessId(66L);

        assertThatThrownBy(() -> service.create(10L, dto, null))
            .isInstanceOf(BusinessException.class)
            .hasMessageContaining("工艺路线不属于当前项目");
        verify(bomRepository, Mockito.never()).insert(any(ProductBom.class));
    }

    @Test
    void listByProjectMarksCurrentFormalBom() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProductBomItemRepository itemRepository = mock(ProductBomItemRepository.class);
        ProductBomRouteRepository routeRepository = mock(ProductBomRouteRepository.class);
        ProductBomRouteFormalSelectionRepository formalSelectionRepository = mock(ProductBomRouteFormalSelectionRepository.class);
        ProductBomServiceImpl service = service(
            productRepository, bomRepository, itemRepository, routeRepository,
            mock(ProductBomRouteColorRepository.class), mock(ProductBomCostSnapshotRepository.class),
            formalSelectionRepository, mock(ProcessRepository.class), mock(OperationLogService.class)
        );
        ProductBom candidate = bom(100L, 10L, "draft");
        candidate.setBomScope("candidate");
        ProductBom selected = bom(101L, 10L, "released");
        selected.setBomScope("formal");
        when(productRepository.selectById(10L)).thenReturn(product(10L));
        when(bomRepository.selectList(Mockito.<Wrapper<ProductBom>>any())).thenReturn(List.of(candidate, selected));
        when(routeRepository.selectList(Mockito.<Wrapper<ProductBomRoute>>any()))
            .thenReturn(List.of(route(300L, 100L, 10L, 66L)), List.of(route(301L, 101L, 10L, 66L)));
        when(formalSelectionRepository.selectList(Mockito.<Wrapper<ProductBomRouteFormalSelection>>any()))
            .thenReturn(List.of(formalSelection(101L)));
        when(itemRepository.selectList(Mockito.<Wrapper<ProductBomItem>>any())).thenReturn(List.of());

        var rows = service.listByProject(10L);

        assertThat(rows).extracting("productBomId", "currentFormal")
            .containsExactly(
                org.assertj.core.groups.Tuple.tuple(100L, false),
                org.assertj.core.groups.Tuple.tuple(101L, true)
            );
    }

    @Test
    void nonFinanceQuantityEditPreservesOriginalAmountsAndNewUnknownIsNotZero() {
        when(amountAccess.hasPermission("finance:write")).thenReturn(false);var products=mock(ProductRepository.class);var boms=mock(ProductBomRepository.class);var items=mock(ProductBomItemRepository.class);var routes=mock(ProductBomRouteRepository.class);
        var service=service(products,boms,items,routes,mock(ProductBomRouteColorRepository.class),mock(ProductBomCostSnapshotRepository.class),mock(ProductBomRouteFormalSelectionRepository.class),mock(ProcessRepository.class),mock(OperationLogService.class));
        var bom=bom(100L,10L,"draft");var old=new ProductBomItem();old.setProductBomItemId(200L);old.setProductBomId(100L);old.setQuantity(new BigDecimal("2"));old.setUnitCostSnapshot(new BigDecimal("4.20"));old.setLineCostSnapshot(new BigDecimal("8.40"));old.setCurrencyCode("MXN");old.setDeletedFlag(0);
        when(boms.selectById(100L)).thenReturn(bom);when(products.selectById(10L)).thenReturn(product(10L));when(items.selectById(200L)).thenReturn(old);when(items.selectList(Mockito.any())).thenReturn(List.of(old));when(routes.selectList(Mockito.any())).thenReturn(List.of());
        var dto=itemDTO(1);dto.setUnitCost(null);dto.setLineCost(null);dto.setCurrencyCode(" ");dto.setQuantity(new BigDecimal("3"));service.updateItem(100L,200L,dto,null);
        assertThat(old.getUnitCostSnapshot()).isEqualByComparingTo("4.20");assertThat(old.getLineCostSnapshot()).isEqualByComparingTo("12.60");assertThat(old.getCurrencyCode()).isEqualTo("MXN");
        service.addItem(100L,dto,null);var inserted=ArgumentCaptor.forClass(ProductBomItem.class);verify(items).insert(inserted.capture());assertThat(inserted.getValue().getUnitCostSnapshot()).isNull();assertThat(inserted.getValue().getLineCostSnapshot()).isNull();assertThat(inserted.getValue().getCurrencyCode()).isNull();
        dto.setUnitCost(BigDecimal.ZERO);assertThatThrownBy(()->service.updateItem(100L,200L,dto,null)).hasMessageContaining("finance:write");verify(items,times(1)).updateById(old);
    }

    @Test
    void directFormalConfirmationRejectsUnreviewedDraftBeforeSelectionOrDelivery() {
        var products=mock(ProductRepository.class);var boms=mock(ProductBomRepository.class);var selections=mock(ProductBomRouteFormalSelectionRepository.class);
        var service=service(products,boms,mock(ProductBomItemRepository.class),mock(ProductBomRouteRepository.class),mock(ProductBomRouteColorRepository.class),mock(ProductBomCostSnapshotRepository.class),selections,mock(ProcessRepository.class),mock(OperationLogService.class));
        ProductBom draft=bom(100L,10L,"draft");draft.setBomScope("candidate");when(boms.selectById(100L)).thenReturn(draft);when(products.selectById(10L)).thenReturn(product(10L));
        assertThatThrownBy(()->service.confirmCurrentVersion(100L,null)).isInstanceOf(BusinessException.class).hasMessageContaining("审核");
        Mockito.verifyNoInteractions(selections,releaseDelivery);verify(boms,Mockito.never()).updateById(any(ProductBom.class));assertThat(draft.getStatus()).isEqualTo("draft");
    }

    @Test
    void confirmCurrentVersionCreatesMultipleFormalSelectionsForSameProcessAndClearsFreeze() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProductBomItemRepository itemRepository = mock(ProductBomItemRepository.class);
        ProductBomRouteRepository routeRepository = mock(ProductBomRouteRepository.class);
        ProductBomRouteColorRepository colorRepository = mock(ProductBomRouteColorRepository.class);
        ProductBomRouteFormalSelectionRepository formalSelectionRepository = mock(ProductBomRouteFormalSelectionRepository.class);
        OperationLogService operationLogService = mock(OperationLogService.class);
        ProductBomServiceImpl service = service(
            productRepository, bomRepository, itemRepository, routeRepository,
            colorRepository, mock(ProductBomCostSnapshotRepository.class),
            formalSelectionRepository, mock(ProcessRepository.class), operationLogService
        );
        ProductBom bom = bom(100L, 10L, "frozen");
        bom.setBomScope("candidate");
        bom.setFrozenFlag(1);
        ProductBomRoute route = route(300L, 100L, 10L, 66L);
        ProductBomRoute secondRoute = route(301L, 100L, 10L, 66L);
        ProductBomRouteFormalSelection previous = formalSelection(99L);
        previous.setProductBomRouteId(300L);
        when(bomRepository.selectById(100L)).thenReturn(bom);
        when(productRepository.selectById(10L)).thenReturn(product(10L));
        when(routeRepository.selectList(Mockito.<Wrapper<ProductBomRoute>>any()))
            .thenReturn(List.of(route, secondRoute), List.of(route, secondRoute));
        when(colorRepository.selectCount(Mockito.any())).thenReturn(1L);
        when(itemRepository.selectCount(Mockito.any())).thenReturn(1L);
        when(itemRepository.selectList(Mockito.<Wrapper<ProductBomItem>>any())).thenReturn(List.of());
        when(formalSelectionRepository.selectList(Mockito.<Wrapper<ProductBomRouteFormalSelection>>any()))
            .thenReturn(List.of(previous), List.of(), List.of(formalSelection(100L)));

        var result = service.confirmCurrentVersion(100L, null);

        assertThat(result.getCurrentFormal()).isTrue();
        assertThat(bom.getBomScope()).isEqualTo("formal");
        assertThat(bom.getStatus()).isEqualTo("released");
        assertThat(bom.getFrozenFlag()).isZero();
        assertThat(bom.getConfirmedAt()).isNotNull();
        assertThat(previous.getStatus()).isEqualTo("invalidated");
        ArgumentCaptor<ProductBomRouteFormalSelection> selectionCaptor =
            ArgumentCaptor.forClass(ProductBomRouteFormalSelection.class);
        verify(formalSelectionRepository, times(2)).insert(selectionCaptor.capture());
        assertThat(selectionCaptor.getAllValues())
            .extracting(ProductBomRouteFormalSelection::getProductBomId)
            .containsOnly(100L);
        assertThat(selectionCaptor.getAllValues())
            .extracting(ProductBomRouteFormalSelection::getProductBomRouteId)
            .containsExactly(300L, 301L);
        verify(operationLogService).logSuccess(any());
        verify(releaseDelivery).released(bom);
    }

    @Test
    void cancelCurrentConfirmationInvalidatesFormalSelection() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProductBomItemRepository itemRepository = mock(ProductBomItemRepository.class);
        ProductBomRouteRepository routeRepository = mock(ProductBomRouteRepository.class);
        ProductBomRouteFormalSelectionRepository formalSelectionRepository = mock(ProductBomRouteFormalSelectionRepository.class);
        ProductBomServiceImpl service = service(
            productRepository, bomRepository, itemRepository, routeRepository,
            mock(ProductBomRouteColorRepository.class), mock(ProductBomCostSnapshotRepository.class),
            formalSelectionRepository, mock(ProcessRepository.class), mock(OperationLogService.class)
        );
        ProductBom bom = bom(100L, 10L, "released");
        bom.setBomScope("formal");
        java.time.LocalDateTime publishedAt=java.time.LocalDateTime.of(2026,10,12,8,0);
        bom.setConfirmedAt(publishedAt);
        ProductBomRouteFormalSelection active = formalSelection(100L);
        when(bomRepository.selectById(100L)).thenReturn(bom);
        when(productRepository.selectById(10L)).thenReturn(product(10L));
        when(formalSelectionRepository.selectList(Mockito.<Wrapper<ProductBomRouteFormalSelection>>any()))
            .thenReturn(List.of(active), List.of(), List.of());
        when(routeRepository.selectList(Mockito.<Wrapper<ProductBomRoute>>any()))
            .thenReturn(List.of(route(300L, 100L, 10L, 66L)));
        when(itemRepository.selectList(Mockito.<Wrapper<ProductBomItem>>any())).thenReturn(List.of());

        var result = service.cancelCurrentConfirmation(100L, null);

        assertThat(result.getCurrentFormal()).isFalse();
        assertThat(bom.getBomScope()).isEqualTo("formal");
        assertThat(bom.getStatus()).isEqualTo("released");
        assertThat(bom.getConfirmedAt()).isEqualTo(publishedAt);
        assertThat(active.getStatus()).isEqualTo("invalidated");
        assertThat(active.getInvalidatedReason()).contains("取消确认");
        verify(formalSelectionRepository).updateById(active);
    }

    @Test
    void deleteVersionSoftDeletesBomGraph() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProductBomItemRepository itemRepository = mock(ProductBomItemRepository.class);
        ProductBomRouteRepository routeRepository = mock(ProductBomRouteRepository.class);
        ProductBomRouteColorRepository colorRepository = mock(ProductBomRouteColorRepository.class);
        ProductBomCostSnapshotRepository costRepository = mock(ProductBomCostSnapshotRepository.class);
        ProductBomRouteFormalSelectionRepository formalSelectionRepository = mock(ProductBomRouteFormalSelectionRepository.class);
        ProductBomServiceImpl service = service(
            productRepository,
            bomRepository,
            itemRepository,
            routeRepository,
            colorRepository,
            costRepository,
            formalSelectionRepository,
            mock(ProcessRepository.class),
            mock(OperationLogService.class)
        );
        when(productRepository.selectById(10L)).thenReturn(product(10L));
        when(bomRepository.selectById(100L)).thenReturn(bom(100L, 10L, "draft"));
        when(formalSelectionRepository.selectList(Mockito.<Wrapper<ProductBomRouteFormalSelection>>any()))
            .thenReturn(List.of());
        when(bomRepository.update(Mockito.isNull(), Mockito.<Wrapper<ProductBom>>any())).thenReturn(1);
        when(routeRepository.update(Mockito.isNull(), Mockito.<Wrapper<ProductBomRoute>>any())).thenReturn(1);
        when(colorRepository.update(Mockito.isNull(), Mockito.<Wrapper<com.yuewei.plm.module.bom.entity.ProductBomRouteColor>>any())).thenReturn(1);
        when(itemRepository.update(Mockito.isNull(), Mockito.<Wrapper<ProductBomItem>>any())).thenReturn(1);
        when(costRepository.update(Mockito.isNull(), Mockito.<Wrapper<com.yuewei.plm.module.bom.entity.ProductBomCostSnapshot>>any())).thenReturn(1);
        when(formalSelectionRepository.update(Mockito.isNull(), Mockito.<Wrapper<ProductBomRouteFormalSelection>>any())).thenReturn(1);

        service.deleteVersion(100L, null);

        verify(bomRepository).update(Mockito.isNull(), Mockito.<Wrapper<ProductBom>>any());
        verify(routeRepository).update(Mockito.isNull(), Mockito.<Wrapper<ProductBomRoute>>any());
        verify(colorRepository).update(Mockito.isNull(), Mockito.<Wrapper<com.yuewei.plm.module.bom.entity.ProductBomRouteColor>>any());
        verify(itemRepository).update(Mockito.isNull(), Mockito.<Wrapper<ProductBomItem>>any());
        verify(costRepository).update(Mockito.isNull(), Mockito.<Wrapper<com.yuewei.plm.module.bom.entity.ProductBomCostSnapshot>>any());
        verify(formalSelectionRepository).update(Mockito.isNull(), Mockito.<Wrapper<ProductBomRouteFormalSelection>>any());
    }

    @Test
    void deleteVersionRejectsCurrentFormalBom() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProductBomRouteFormalSelectionRepository formalSelectionRepository = mock(ProductBomRouteFormalSelectionRepository.class);
        ProductBomServiceImpl service = service(
            productRepository,
            bomRepository,
            mock(ProductBomItemRepository.class),
            mock(ProductBomRouteRepository.class),
            mock(ProductBomRouteColorRepository.class),
            mock(ProductBomCostSnapshotRepository.class),
            formalSelectionRepository,
            mock(ProcessRepository.class),
            mock(OperationLogService.class)
        );
        when(productRepository.selectById(10L)).thenReturn(product(10L));
        when(bomRepository.selectById(100L)).thenReturn(bom(100L, 10L, "draft"));
        when(formalSelectionRepository.selectList(Mockito.<Wrapper<ProductBomRouteFormalSelection>>any()))
            .thenReturn(List.of(formalSelection(100L)));

        assertThatThrownBy(() -> service.deleteVersion(100L, null))
            .isInstanceOf(BusinessException.class)
            .extracting("code")
            .isEqualTo(ErrorCodeConstants.VALIDATION_ERROR);
    }

    private Product product(Long productId) {
        Product product = new Product();
        product.setProductId(productId);
        product.setProductCode("PRD-1");
        product.setProductName("超队3.0");
        product.setDeletedFlag(0);
        return product;
    }

    private ProductBom bom(Long bomId, Long productId, String status) {
        ProductBom bom = new ProductBom();
        bom.setProductBomId(bomId);
        bom.setProductId(productId);
        bom.setBomCode("BOM-1");
        bom.setBomName("样品BOM");
        bom.setBomType("ebom");
        bom.setVersionNo("A");
        bom.setStatus(status);
        bom.setDeletedFlag(0);
        return bom;
    }

    private ProcessEntity routeProcess(Long processId, Long productId) {
        ProcessEntity process = new ProcessEntity();
        process.setProcessId(processId);
        process.setProductId(productId);
        process.setProcessCode("ROUTE-DYE");
        process.setProcessName("染色路线");
        process.setProcessType("routing");
        process.setStatus("draft");
        process.setDeletedFlag(0);
        return process;
    }

    private ProductBomRoute route(Long routeId, Long bomId, Long productId, Long processId) {
        ProductBomRoute route = new ProductBomRoute();
        route.setProductBomRouteId(routeId);
        route.setProductBomId(bomId);
        route.setProductId(productId);
        route.setProcessId(processId);
        route.setRouteCode("ROUTE-DYE");
        route.setRouteName("染色路线");
        route.setStatus("active");
        route.setDeletedFlag(0);
        return route;
    }

    private ProductBomItemDTO itemDTO(Integer lineNo) {
        ProductBomItemDTO dto = new ProductBomItemDTO();
        dto.setLineNo(lineNo);
        dto.setInventoryId(1L);
        dto.setItemCode("MAT-001");
        dto.setItemName("TPU 原料");
        dto.setQuantity(new BigDecimal("0.08"));
        dto.setUnit("kg");
        dto.setLossRate(new BigDecimal("0.02"));
        dto.setSupplierCode("SUP-A");
        dto.setSupplierName("东莞塑胶 A");
        dto.setUnitCost(new BigDecimal("3.50"));
        dto.setSubstituteFlag(0);
        return dto;
    }

    private ProductBomRouteFormalSelection formalSelection(Long bomId) {
        ProductBomRouteFormalSelection value = new ProductBomRouteFormalSelection();
        value.setProductId(10L);
        value.setProductBomId(bomId);
        value.setProductBomRouteId(301L);
        value.setProcessId(66L);
        value.setStatus("active");
        value.setDeletedFlag(0);
        return value;
    }
}
