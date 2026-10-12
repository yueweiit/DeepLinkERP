package com.yuewei.plm.module.bom.service.impl;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.module.bom.dto.BomRouteColorDTO;
import com.yuewei.plm.module.bom.repository.ProductBomImportBatchRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteRepository;
import com.yuewei.plm.module.bom.entity.ProductBomRoute;
import com.yuewei.plm.module.bom.dto.BomRouteSaveDTO;
import com.yuewei.plm.module.pilot.PilotAccessService;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.module.bom.entity.ProductBom;
import com.yuewei.plm.module.bom.entity.ProductBomImportBatch;
import com.yuewei.plm.module.bom.service.BomMaterialLookup;
import com.yuewei.plm.module.bom.service.BomProcessRouteLookup;
import com.yuewei.plm.module.bom.service.ProductBomWorkflowService;
import com.yuewei.plm.module.bom.vo.BomImportRowVO;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.Optional;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.junit.jupiter.api.Test;
import com.yuewei.plm.module.code.entity.CodeItem;
import com.yuewei.plm.module.code.repository.CodeItemRepository;
import com.baomidou.mybatisplus.core.conditions.Wrapper;
import java.util.List;
import org.mockito.ArgumentCaptor;

class BomImportServiceImplTest {

    @Test
    void previewsValidWorkbookWithoutWritingBomRows() throws Exception {
        ProductBomImportBatchRepository batchRepository = mock(ProductBomImportBatchRepository.class);
        ProductBomRepository bomRepository = editableBomRepository();
        BomMaterialLookup materialLookup = mock(BomMaterialLookup.class);
        ProductBomWorkflowService workflowService = mock(ProductBomWorkflowService.class);
        BomProcessRouteLookup routeLookup = mock(BomProcessRouteLookup.class);
        when(materialLookup.findByCode("MAT-001")).thenReturn(Optional.of(
            new BomMaterialLookup.Material(1L, "MAT-001", "TPU 原料", null, "kg", "东莞塑胶 A",
                new BigDecimal("12.50"), "CNY")
        ));
        when(routeLookup.findByCode(10L, "DYE")).thenReturn(Optional.of(
            new BomProcessRouteLookup.Route(100L, "DYE", "染色路线")
        ));
        BomImportServiceImpl service = new BomImportServiceImpl(
            batchRepository, bomRepository, materialLookup, routeLookup, workflowService, colorCodes(), mock(ProductBomRouteRepository.class), access(true)
        );

        var preview = service.preview(10L, 20L, "formal.xlsx", workbook(true));

        assertThat(preview.getStatus()).isEqualTo("ready");
        assertThat(preview.getValidRows()).isEqualTo(1);
        assertThat(preview.getErrors()).isEmpty();
        assertThat(preview.getRows().get(0).getProcessId()).isEqualTo(100L);
        assertThat(preview.getImportToken()).isNotBlank();
    }

    @Test
    void candidateImportAllowsUnmatchedMaterialAsManualReadyRow() throws Exception {
        ProductBomImportBatchRepository batchRepository = mock(ProductBomImportBatchRepository.class);
        ProductBomRepository bomRepository = editableBomRepository("candidate");
        BomMaterialLookup materialLookup = mock(BomMaterialLookup.class);
        ProductBomWorkflowService workflowService = mock(ProductBomWorkflowService.class);
        BomProcessRouteLookup routeLookup = mock(BomProcessRouteLookup.class);
        when(materialLookup.findByCode("MAT-001")).thenReturn(Optional.empty());
        when(routeLookup.findByCode(10L, "DYE")).thenReturn(Optional.of(
            new BomProcessRouteLookup.Route(100L, "DYE", "染色路线")
        ));
        BomImportServiceImpl service = new BomImportServiceImpl(
            batchRepository, bomRepository, materialLookup, routeLookup, workflowService, colorCodes(), mock(ProductBomRouteRepository.class), access(true)
        );

        var preview = service.preview(10L, 20L, "candidate.xlsx", workbook(true));

        assertThat(preview.getStatus()).isEqualTo("ready");
        assertThat(preview.getValidRows()).isEqualTo(1);
        assertThat(preview.getErrors()).isEmpty();
        assertThat(preview.getRows().get(0).getMaterialSource()).isEqualTo("manual");
        assertThat(preview.getRows().get(0).getUnmatchedFlag()).isEqualTo(1);
        assertThat(preview.getRows().get(0).getLookupMessage()).contains("未匹配");
        assertThat(preview.getRows().get(0).getItemName()).isEqualTo("TPU 原料");
        assertThat(preview.getRows().get(0).getLineCost()).isEqualByComparingTo("25.00");
        verify(batchRepository).insert(any(ProductBomImportBatch.class));
    }

    @Test
    void commitKeepsCandidateDraftAndDoesNotImplicitlyPublish() throws Exception {
        ProductBomImportBatchRepository batchRepository = mock(ProductBomImportBatchRepository.class);
        ProductBomRepository bomRepository = editableBomRepository("candidate");
        ProductBomWorkflowService workflowService = mock(ProductBomWorkflowService.class);
        ProductBomImportBatch batch = new ProductBomImportBatch();
        batch.setProductBomImportBatchId(1L);
        batch.setProductBomId(20L);
        batch.setProductId(10L);
        batch.setImportToken("token");
        batch.setStatus("ready");
        batch.setExpiresAt(LocalDateTime.now().plusHours(1));
        batch.setDeletedFlag(0);
        batch.setPreviewJson(new ObjectMapper().writeValueAsString(List.of(importRow())));
        when(batchRepository.selectOne(any(Wrapper.class))).thenReturn(batch);
        when(batchRepository.update(any(ProductBomImportBatch.class), any(Wrapper.class))).thenReturn(1);
        BomImportServiceImpl service = new BomImportServiceImpl(
            batchRepository, bomRepository, mock(BomMaterialLookup.class), mock(BomProcessRouteLookup.class),
            workflowService, colorCodes(), mock(ProductBomRouteRepository.class), access(true)
        );

        service.commit("token");

        org.mockito.Mockito.verify(bomRepository, org.mockito.Mockito.never()).updateById(any(ProductBom.class));
        verify(workflowService).saveRoutes(org.mockito.ArgumentMatchers.eq(20L), any());
        org.mockito.Mockito.verifyNoMoreInteractions(workflowService);
        assertThat(bomRepository.selectById(20L).getStatus()).isEqualTo("draft");
        assertThat(bomRepository.selectById(20L).getBomScope()).isEqualTo("candidate");
        assertThat(batch.getCommittedBy()).isEqualTo("import-engineer");
    }

    @Test
    void invalidHeaderProducesDownloadableErrorWorkbook() throws Exception {
        ProductBomImportBatchRepository batchRepository = mock(ProductBomImportBatchRepository.class);
        BomImportServiceImpl service = new BomImportServiceImpl(
            batchRepository, editableBomRepository(), mock(BomMaterialLookup.class), mock(BomProcessRouteLookup.class),
            mock(ProductBomWorkflowService.class), colorCodes(), mock(ProductBomRouteRepository.class), access(true)
        );

        var preview = service.preview(10L, 20L, "broken.xlsx", workbook(false));
        byte[] report = service.buildErrorReport(preview.getErrors());

        assertThat(preview.getStatus()).isEqualTo("invalid");
        assertThat(preview.getErrors()).extracting("field").contains("表头");
        assertThat(report).isNotEmpty();
        try (XSSFWorkbook workbook = new XSSFWorkbook(new ByteArrayInputStream(report))) {
            assertThat(workbook.getSheetAt(0).getRow(0).getCell(3).getStringCellValue()).isEqualTo("错误原因");
        }
    }

    @Test
    void rejectsBomOwnedByAnotherProductBeforeParsing() throws Exception {
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProductBom bom = new ProductBom();
        bom.setProductId(99L);
        bom.setBomScope("formal");
        bom.setStatus("draft");
        when(bomRepository.selectById(20L)).thenReturn(bom);
        BomImportServiceImpl service = new BomImportServiceImpl(
            mock(ProductBomImportBatchRepository.class), bomRepository, mock(BomMaterialLookup.class),
            mock(BomProcessRouteLookup.class), mock(ProductBomWorkflowService.class), colorCodes(), mock(ProductBomRouteRepository.class), access(true)
        );

        org.assertj.core.api.Assertions.assertThatThrownBy(() -> service.preview(10L, 20L, "formal.xlsx", workbook(true)))
            .isInstanceOf(com.yuewei.plm.common.exception.BusinessException.class)
            .hasMessageContaining("BOM");
    }

    @Test
    void engineeringImportAllowsUnpricedMaterialsButRejectsWorkbookPricesAndPricedTokenCommit() throws Exception {
        var batches = mock(ProductBomImportBatchRepository.class);
        var materials = mock(BomMaterialLookup.class);
        var processRoutes = mock(BomProcessRouteLookup.class);
        var workflow = mock(ProductBomWorkflowService.class);
        var targetRoutes = mock(ProductBomRouteRepository.class);
        when(materials.findByCode("MAT-001")).thenReturn(Optional.of(new BomMaterialLookup.Material(1L, "MAT-001", "TPU", null, "kg", "供应商", new BigDecimal("12.5"), "CNY")));
        when(processRoutes.findByCode(10L, "DYE")).thenReturn(Optional.of(new BomProcessRouteLookup.Route(100L, "DYE", "染色路线")));
        var service = new BomImportServiceImpl(batches, editableBomRepository("candidate"), materials, processRoutes, workflow, colorCodes(), targetRoutes, access(false));
        var preview = service.preview(10L, 20L, "engineering.xlsx", workbook(true, false));
        assertThat(preview.getStatus()).isEqualTo("ready");
        var unpriced = preview.getRows().get(0);
        assertThat(unpriced.getUnitCost()).isNull();
        assertThat(unpriced.getLineCost()).isNull();
        assertThat(unpriced.getCurrencyCode()).isNull();
        var batchCapture = ArgumentCaptor.forClass(ProductBomImportBatch.class);
        verify(batches).insert(batchCapture.capture());
        var batch = batchCapture.getValue();
        batch.setProductBomImportBatchId(31L);
        String unpricedJson = batch.getPreviewJson();
        when(batches.selectOne(any(Wrapper.class))).thenReturn(batch);
        assertThatThrownBy(() -> service.preview(10L, 20L, "priced.xlsx", workbook(true)))
            .isInstanceOf(BusinessException.class).hasMessageContaining("finance:write");
        // No JSON amount is sent by commit(token); authority comes from the stored server preview.
        batch.setPreviewJson(new ObjectMapper().writeValueAsString(List.of(importRow())));
        assertThatThrownBy(() -> service.commit(preview.getImportToken()))
            .isInstanceOf(BusinessException.class).hasMessageContaining("finance:write");
        org.mockito.Mockito.verify(batches, org.mockito.Mockito.never()).update(any(ProductBomImportBatch.class), any(Wrapper.class));
        org.mockito.Mockito.verifyNoInteractions(workflow);
        batch.setPreviewJson(unpricedJson);
        var target = new ProductBomRoute();
        target.setProductBomRouteId(12L);target.setProductBomId(20L);target.setProcessId(100L);
        when(targetRoutes.selectList(any(Wrapper.class))).thenReturn(List.of(target));
        when(batches.update(any(ProductBomImportBatch.class), any(Wrapper.class))).thenReturn(1);
        service.commit(preview.getImportToken());
        var savedRoutes = ArgumentCaptor.forClass(List.class);
        verify(workflow).saveRoutes(org.mockito.ArgumentMatchers.eq(20L), savedRoutes.capture());
        var saved = (BomRouteSaveDTO) savedRoutes.getValue().get(0);
        assertThat(saved.getProductBomRouteId()).isEqualTo(12L);
        assertThat(saved.getItems().get(0).getLineNo()).isEqualTo(1);
        assertThat(saved.getItems().get(0).getUnitCost()).isNull();
        assertThat(saved.getItems().get(0).getLineCost()).isNull();
        assertThat(saved.getItems().get(0).getCurrencyCode()).isNull();
        assertThat(batch.getCommittedBy()).isEqualTo("import-engineer");
    }

    private ProductBomRepository editableBomRepository() {
        return editableBomRepository("formal");
    }

    static PilotAccessService access(boolean moneyWrite) {
        PilotAccessService access = mock(PilotAccessService.class);
        when(access.actor()).thenReturn(new CurrentUser(18L, "import-engineer", "工程", false));
        when(access.hasPermission("finance:write")).thenReturn(moneyWrite);
        if (!moneyWrite) org.mockito.Mockito.doThrow(new BusinessException(40103, "没有权限：finance:write")).when(access).requireFinanceWrite();
        return access;
    }

    private ProductBomRepository editableBomRepository(String bomScope) {
        ProductBomRepository repository = mock(ProductBomRepository.class);
        ProductBom bom = new ProductBom();
        bom.setProductBomId(20L);
        bom.setProductId(10L);
        bom.setBomScope(bomScope);
        bom.setStatus("draft");
        bom.setFrozenFlag(0);
        when(repository.selectById(20L)).thenReturn(bom);
        return repository;
    }

    private BomImportRowVO importRow() {
        BomRouteColorDTO color = new BomRouteColorDTO();
        color.setCodeItemId(2L);
        color.setCodeValue("02");
        color.setCodeName("Negro");
        BomImportRowVO row = new BomImportRowVO();
        row.setLineNo(1);
        row.setProcessId(100L);
        row.setRouteCode("DYE");
        row.setRouteName("Dye route");
        row.setColors(List.of("Negro"));
        row.setColorItems(List.of(color));
        row.setInventoryId(1L);
        row.setItemCode("MAT-001");
        row.setItemName("Material");
        row.setUnit("kg");
        row.setQuantity(BigDecimal.ONE);
        row.setLossRate(BigDecimal.ZERO);
        row.setUnitCost(BigDecimal.ONE);
        row.setLineCost(BigDecimal.ONE);
        row.setCurrencyCode("CNY");
        row.setSubstituteFlag(0);
        return row;
    }

    private byte[] workbook(boolean validHeader) throws Exception {
        return workbook(validHeader, true);
    }

    private byte[] workbook(boolean validHeader, boolean priced) throws Exception {
        try (XSSFWorkbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            var sheet = workbook.createSheet("BOM导入");
            var header = sheet.createRow(0);
            String[] headers = {
                "行号", "路线编码", "路线名称", "适用颜色", "物料编码", "物料名称",
                "规格", "单位", "用量", "供应商", "单价", "单个成本", "损耗率", "替代料标识", "备注"
            };
            for (int index = 0; index < headers.length; index++) {
                header.createCell(index).setCellValue(index == 0 && !validHeader ? "错误列" : headers[index]);
            }
            var row = sheet.createRow(1);
            row.createCell(0).setCellValue(1);
            row.createCell(1).setCellValue("DYE");
            row.createCell(2).setCellValue("染色路线");
            row.createCell(3).setCellValue("02,08");
            row.createCell(4).setCellValue("MAT-001");
            row.createCell(5).setCellValue("TPU 原料");
            row.createCell(7).setCellValue("kg");
            row.createCell(8).setCellValue(2);
            row.createCell(9).setCellValue("东莞塑胶 A");
            if (priced) {
                row.createCell(10).setCellValue(12.5);
                row.createCell(11).setCellValue(25);
            }
            row.createCell(12).setCellValue(0.05);
            workbook.write(output);
            return output.toByteArray();
        }
    }

    private CodeItemRepository colorCodes() {
        CodeItemRepository repository = mock(CodeItemRepository.class);
        when(repository.selectOne(any(Wrapper.class))).thenReturn(color(2L, "02", "Negro"), color(8L, "08", "Azul Rey"));
        return repository;
    }

    private CodeItem color(Long id, String code, String name) {
        CodeItem item = new CodeItem(); item.setCodeItemId(id); item.setCodeType("color"); item.setCodeValue(code);
        item.setCodeName(name); item.setStatus("enabled"); item.setDeletedFlag(0); return item;
    }
}
