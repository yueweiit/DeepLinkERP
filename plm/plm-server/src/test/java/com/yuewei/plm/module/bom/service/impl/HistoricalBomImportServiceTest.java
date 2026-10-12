package com.yuewei.plm.module.bom.service.impl;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.module.bom.entity.ProductBom;
import com.yuewei.plm.module.bom.entity.ProductBomImportBatch;
import com.yuewei.plm.module.bom.repository.ProductBomImportBatchRepository;
import com.yuewei.plm.module.bom.repository.ProductBomItemRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteColorRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteRepository;
import com.yuewei.plm.module.bom.service.BomMaterialLookup;
import com.yuewei.plm.module.bom.service.BomProcessRouteLookup;
import com.yuewei.plm.module.bom.service.ProductBomWorkflowService;
import com.yuewei.plm.module.bom.vo.BomImportErrorVO;
import com.yuewei.plm.module.bom.vo.BomImportRowVO;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import com.yuewei.plm.module.code.entity.CodeItem;
import com.yuewei.plm.module.code.repository.CodeItemRepository;
import java.io.ByteArrayOutputStream;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.junit.jupiter.api.Test;

class HistoricalBomImportServiceTest {
    @Test
    void previewMatchesUniqueProductCodeAndBuildsReadyBatch() throws Exception {
        ProductRepository products = mock(ProductRepository.class);
        when(products.selectList(any(Wrapper.class))).thenReturn(List.of(product(10L, "P-LJ")));
        BomMaterialLookup materials = mock(BomMaterialLookup.class);
        when(materials.findByCode("MAT-001")).thenReturn(Optional.of(
            new BomMaterialLookup.Material(1L, "MAT-001", "TPU", null, "kg", "东莞塑胶 A",
                new BigDecimal("12.50"), "CNY")));
        BomProcessRouteLookup routes = mock(BomProcessRouteLookup.class);
        when(routes.findByCode(10L, "DYE")).thenReturn(Optional.of(
            new BomProcessRouteLookup.Route(100L, "DYE", "染色路线")));
        var access = BomImportServiceImplTest.access(true);
        HistoricalBomImportService service = new HistoricalBomImportService(
            mock(ProductBomImportBatchRepository.class), mock(ProductBomRepository.class),
            mock(ProductBomRouteRepository.class), mock(ProductBomRouteColorRepository.class), mock(ProductBomItemRepository.class), products,
            materials, routes, mock(ProductBomWorkflowService.class), colorCodes(), access);

        var preview = service.preview("history.xlsx", workbook());

        assertThat(preview.getStatus()).isEqualTo("ready");
        assertThat(preview.getValidRows()).isEqualTo(1);
        assertThat(preview.getRows().get(0).getProductCode()).isEqualTo("P-LJ");
        assertThat(preview.getRows().get(0).getVersionNo()).isEqualTo("V1");
        org.mockito.Mockito.doThrow(new com.yuewei.plm.common.exception.BusinessException(40103, "没有权限：finance:write")).when(access).requireFinanceWrite();
        org.assertj.core.api.Assertions.assertThatThrownBy(() -> service.preview("history.xlsx", workbook()))
            .isInstanceOf(com.yuewei.plm.common.exception.BusinessException.class).hasMessageContaining("finance:write");
    }

    @Test
    void previewRejectsAmbiguousProductCode() throws Exception {
        ProductRepository products = mock(ProductRepository.class);
        when(products.selectList(any(Wrapper.class))).thenReturn(List.of(product(10L, "P-LJ"), product(11L, "P-LJ")));
        HistoricalBomImportService service = new HistoricalBomImportService(
            mock(ProductBomImportBatchRepository.class), mock(ProductBomRepository.class),
            mock(ProductBomRouteRepository.class), mock(ProductBomRouteColorRepository.class), mock(ProductBomItemRepository.class), products,
            mock(BomMaterialLookup.class), mock(BomProcessRouteLookup.class), mock(ProductBomWorkflowService.class), colorCodes(), BomImportServiceImplTest.access(true));

        var preview = service.preview("history.xlsx", workbook());

        assertThat(preview.getStatus()).isEqualTo("invalid");
        assertThat(preview.getErrors()).extracting(BomImportErrorVO::getReason)
            .anyMatch(value -> value.contains("多个产品"));
    }

    @Test
    void previewAcceptsErpBomOverviewWithPlaceholderDefaults() throws Exception {
        ProductRepository products = mock(ProductRepository.class);
        when(products.selectList(any(Wrapper.class))).thenReturn(List.of(), List.of(product(10L, "NBA4030")));
        ProductBomRepository boms = mock(ProductBomRepository.class);
        when(boms.selectList(any(Wrapper.class))).thenReturn(List.of());
        HistoricalBomImportService service = new HistoricalBomImportService(
            mock(ProductBomImportBatchRepository.class), boms,
            mock(ProductBomRouteRepository.class), mock(ProductBomRouteColorRepository.class), mock(ProductBomItemRepository.class), products,
            mock(BomMaterialLookup.class), mock(BomProcessRouteLookup.class), mock(ProductBomWorkflowService.class), colorCodes(), BomImportServiceImplTest.access(true));

        var preview = service.preview("Gestion BOM.xlsx", erpOverviewWorkbook());

        assertThat(preview.getStatus()).isEqualTo("ready");
        assertThat(preview.getValidRows()).isEqualTo(1);
        assertThat(preview.getRows().get(0).getProductCode()).isEqualTo("NBA4030");
        assertThat(preview.getRows().get(0).getBomCode()).isEqualTo("BOM-NBA4030000001-002");
        assertThat(preview.getRows().get(0).getRouteCode()).isEqualTo("--");
        assertThat(preview.getRows().get(0).getItemCode()).isEqualTo("--");
        assertThat(preview.getRows().get(0).getQuantity()).isEqualByComparingTo(BigDecimal.ONE);
        assertThat(preview.getRows().get(0).getLineCost()).isNull();
        assertThat(preview.getRows().get(0).getRemark()).contains("components=10", "associated_skus=70");
    }

    @Test
    void commitCreatesReleasedErpArchiveBomWithPlaceholders() throws Exception {
        ProductBomImportBatchRepository batches = mock(ProductBomImportBatchRepository.class);
        ProductBomRepository boms = mock(ProductBomRepository.class);
        ProductBomRouteRepository routes = mock(ProductBomRouteRepository.class);
        ProductBomRouteColorRepository colors = mock(ProductBomRouteColorRepository.class);
        ProductBomItemRepository items = mock(ProductBomItemRepository.class);
        ProductBomImportBatch batch = new ProductBomImportBatch();
        batch.setProductBomImportBatchId(20L);
        batch.setImportToken("token");
        batch.setBomScope("history");
        batch.setStatus("ready");
        batch.setDeletedFlag(0);
        batch.setExpiresAt(LocalDateTime.now().plusHours(1));
        BomImportRowVO row = new BomImportRowVO();
        row.setProductId(10L);
        row.setProductCode("NBA4030");
        row.setBomCode("BOM-NBA4030000001-002");
        row.setVersionNo(row.getBomCode());
        row.setSourceParentCode("NBA4030000001");
        row.setSourceParentName("亮甲2.0");
        row.setSourceOrigin("erp");
        row.setSourceStatus("Activo");
        row.setSpecification("MORADO");
        row.setComponentCount(10);
        row.setAssociatedSkuCount(70);
        batch.setPreviewJson(new ObjectMapper().writeValueAsString(List.of(row)));
        when(batches.selectOne(any(Wrapper.class))).thenReturn(batch);
        when(batches.update(any(ProductBomImportBatch.class), any(Wrapper.class))).thenReturn(1);
        when(boms.insert(any(ProductBom.class))).thenAnswer(invocation -> {
            invocation.getArgument(0, ProductBom.class).setProductBomId(30L);
            return 1;
        });
        when(routes.insert(any(com.yuewei.plm.module.bom.entity.ProductBomRoute.class))).thenAnswer(invocation -> {
            var route = invocation.getArgument(0, com.yuewei.plm.module.bom.entity.ProductBomRoute.class);
            route.setProductBomRouteId(40L);
            return 1;
        });
        HistoricalBomImportService service = new HistoricalBomImportService(
            batches, boms, routes, colors, items, mock(ProductRepository.class),
            mock(BomMaterialLookup.class), mock(BomProcessRouteLookup.class),
            mock(ProductBomWorkflowService.class), colorCodes(), BomImportServiceImplTest.access(false));

        row.setUnitCost(BigDecimal.ZERO);
        batch.setPreviewJson(new ObjectMapper().writeValueAsString(List.of(row)));
        org.assertj.core.api.Assertions.assertThatThrownBy(() -> service.commit("token"))
            .isInstanceOf(com.yuewei.plm.common.exception.BusinessException.class).hasMessageContaining("finance:write");
        org.mockito.Mockito.verify(items, org.mockito.Mockito.never()).insert(any(com.yuewei.plm.module.bom.entity.ProductBomItem.class));
        row.setUnitCost(null);
        batch.setPreviewJson(new ObjectMapper().writeValueAsString(List.of(row)));
        service.commit("token");

        verify(boms).insert(any(ProductBom.class));
        verify(routes).insert(any(com.yuewei.plm.module.bom.entity.ProductBomRoute.class));
        verify(colors).insert(any(com.yuewei.plm.module.bom.entity.ProductBomRouteColor.class));
        verify(items).insert(any(com.yuewei.plm.module.bom.entity.ProductBomItem.class));
        assertThat(batch.getStatus()).isEqualTo("committed");
        assertThat(batch.getCommittedBy()).isEqualTo("import-engineer");
    }

    private Product product(Long id, String code) {
        Product value = new Product();
        value.setProductId(id);
        value.setProductCode(code);
        value.setProductName("亮甲");
        value.setStatus("released");
        value.setDeletedFlag(0);
        return value;
    }

    private byte[] workbook() throws Exception {
        try (XSSFWorkbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            var sheet = workbook.createSheet("历史BOM导入");
            String[] headers = {"产品编码", "BOM版本", "行号", "路线编码", "路线名称", "适用颜色", "物料编码", "物料名称", "规格", "单位", "用量", "供应商", "单价", "单个成本", "损耗率", "替代料标识", "备注"};
            var header = sheet.createRow(0);
            for (int index = 0; index < headers.length; index++) header.createCell(index).setCellValue(headers[index]);
            var row = sheet.createRow(1);
            row.createCell(0).setCellValue("P-LJ");
            row.createCell(1).setCellValue("V1");
            row.createCell(2).setCellValue(1);
            row.createCell(3).setCellValue("DYE");
            row.createCell(4).setCellValue("染色路线");
            row.createCell(5).setCellValue("02,08");
            row.createCell(6).setCellValue("MAT-001");
            row.createCell(7).setCellValue("TPU");
            row.createCell(9).setCellValue("kg");
            row.createCell(10).setCellValue(2);
            row.createCell(11).setCellValue("东莞塑胶 A");
            row.createCell(12).setCellValue(12.5);
            row.createCell(13).setCellValue(25);
            row.createCell(14).setCellValue(0.05);
            workbook.write(output);
            return output.toByteArray();
        }
    }

    private byte[] erpOverviewWorkbook() throws Exception {
        try (XSSFWorkbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            var sheet = workbook.createSheet("Gestión BOM");
            sheet.createRow(0).createCell(1).setCellValue("YUEWEI, S.A. DE C.V.");
            var header = sheet.createRow(5);
            String[] headers = {"Código BOM", "Código padre", "Nombre padre", "Componentes", "SKUs asociados", "Estado", "Especificación", "Origen"};
            for (int index = 0; index < headers.length; index++) header.createCell(index).setCellValue(headers[index]);
            var row = sheet.createRow(6);
            row.createCell(0).setCellValue("BOM-NBA4030000001-002");
            row.createCell(1).setCellValue("NBA4030000001");
            row.createCell(2).setCellValue("亮甲2.0");
            row.createCell(3).setCellValue(10);
            row.createCell(4).setCellValue(70);
            row.createCell(5).setCellValue("Activo");
            row.createCell(6).setCellValue("MORADO");
            row.createCell(7).setCellValue("erp");
            workbook.write(output);
            return output.toByteArray();
        }
    }

    private CodeItemRepository colorCodes() {
        CodeItemRepository repository = mock(CodeItemRepository.class);
        CodeItem black = color(2L, "02", "Negro");
        CodeItem blue = color(8L, "08", "Azul Rey");
        when(repository.selectOne(any(Wrapper.class))).thenReturn(black, blue);
        return repository;
    }

    private CodeItem color(Long id, String code, String name) {
        CodeItem item = new CodeItem();
        item.setCodeItemId(id); item.setCodeType("color"); item.setCodeValue(code);
        item.setCodeName(name); item.setStatus("enabled"); item.setDeletedFlag(0);
        return item;
    }
}
