package com.yuewei.plm.module.importexport.service.impl;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.process.entity.ProcessEntity;
import com.yuewei.plm.module.process.repository.ProcessRepository;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.sql.SQLException;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;
import org.apache.poi.ss.usermodel.WorkbookFactory;
import org.apache.poi.hssf.usermodel.HSSFWorkbook;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.BadSqlGrammarException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.PreparedStatementCreator;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.mock.web.MockMultipartFile;

class MasterDataImportExportServiceImplTest {

    @Test
    void productTemplateUsesDocumentedSeedImportHeaders() throws Exception {
        MasterDataImportExportServiceImpl service = new MasterDataImportExportServiceImpl(
            mock(ProductRepository.class),
            mock(ProcessRepository.class),
            new CapturingJdbcTemplate(),
            mock(OperationLogService.class)
        );

        byte[] bytes = service.template("product");

        try (var workbook = WorkbookFactory.create(new ByteArrayInputStream(bytes))) {
            var header = workbook.getSheet("product_template").getRow(0);
            List<String> headers = java.util.stream.IntStream.range(0, header.getLastCellNum())
                .mapToObj(index -> header.getCell(index).getStringCellValue())
                .toList();
            assertThat(headers).containsExactly(
                "product_code",
                "product_name",
                "product_type",
                "parent_product_code",
                "series_name",
                "model",
                "color",
                "version_no",
                "status",
                "current_stage",
                "remark"
            );
        }
    }

    @Test
    void inventoryTemplateUsesScreenshotMaterialImportHeaders() throws Exception {
        MasterDataImportExportServiceImpl service = new MasterDataImportExportServiceImpl(
            mock(ProductRepository.class),
            mock(ProcessRepository.class),
            new CapturingJdbcTemplate(),
            mock(OperationLogService.class)
        );

        byte[] bytes = service.template("inventory");

        try (var workbook = WorkbookFactory.create(new ByteArrayInputStream(bytes))) {
            var header = workbook.getSheet("inventory_template").getRow(0);
            List<String> headers = java.util.stream.IntStream.range(0, header.getLastCellNum())
                .mapToObj(index -> header.getCell(index).getStringCellValue())
                .toList();
            assertThat(headers).containsExactly(
                "物料组",
                "物料编码",
                "物料名称",
                "规格型号",
                "规格",
                "新增日期"
            );
        }
    }

    @Test
    void processPreviewAcceptsChineseTemplateHeaders() throws Exception {
        ProductRepository productRepository = mock(ProductRepository.class);
        Product product = new Product();
        product.setProductId(100L);
        when(productRepository.selectOne(any())).thenReturn(product);
        MasterDataImportExportServiceImpl service = new MasterDataImportExportServiceImpl(
            productRepository,
            mock(ProcessRepository.class),
            new CapturingJdbcTemplate(),
            mock(OperationLogService.class)
        );

        var preview = service.preview("process", workbookWithChineseProcessHeaders());

        assertThat(preview.getSuccessCount()).isEqualTo(1);
        assertThat(preview.getRows()).hasSize(1);
        assertThat(preview.getRows().get(0).getValues()).containsEntry("process_code", "PROC-CN-001");
        assertThat(preview.getRows().get(0).getValues()).containsEntry("process_name", "喷油");
    }

    @Test
    void processPreviewUsesProcessTemplateSheetWhenWorkbookHasNotesSheetFirst() throws Exception {
        ProductRepository productRepository = mock(ProductRepository.class);
        Product product = new Product();
        product.setProductId(100L);
        when(productRepository.selectOne(any())).thenReturn(product);
        MasterDataImportExportServiceImpl service = new MasterDataImportExportServiceImpl(
            productRepository,
            mock(ProcessRepository.class),
            new CapturingJdbcTemplate(),
            mock(OperationLogService.class)
        );

        var preview = service.preview("process", workbookWithNotesBeforeProcessTemplate());

        assertThat(preview.getSuccessCount()).isEqualTo(1);
        assertThat(preview.getRows()).hasSize(1);
        assertThat(preview.getRows().get(0).getValues()).containsEntry("product_code", "PRD-NOTES-001");
        assertThat(preview.getRows().get(0).getValues()).containsEntry("process_code", "PROC-NOTES-001");
    }

    @Test
    void processPreviewScansTemplateSheetForHeaderRow() throws Exception {
        ProductRepository productRepository = mock(ProductRepository.class);
        Product product = new Product();
        product.setProductId(100L);
        when(productRepository.selectOne(any())).thenReturn(product);
        MasterDataImportExportServiceImpl service = new MasterDataImportExportServiceImpl(
            productRepository,
            mock(ProcessRepository.class),
            new CapturingJdbcTemplate(),
            mock(OperationLogService.class)
        );

        var preview = service.preview("process", workbookWithBlankRowBeforeProcessHeaders());

        assertThat(preview.getSuccessCount()).isEqualTo(1);
        assertThat(preview.getRows()).hasSize(1);
        assertThat(preview.getRows().get(0).getRowNo()).isEqualTo(3);
        assertThat(preview.getRows().get(0).getValues()).containsEntry("product_code", "PRD-SCAN-001");
        assertThat(preview.getRows().get(0).getValues()).containsEntry("process_code", "PROC-SCAN-001");
    }

    @Test
    void processPreviewNormalizesLegacyActiveStatusToConfirmed() throws Exception {
        ProductRepository productRepository = mock(ProductRepository.class);
        Product product = new Product();
        product.setProductId(100L);
        when(productRepository.selectOne(any())).thenReturn(product);
        MasterDataImportExportServiceImpl service = new MasterDataImportExportServiceImpl(
            productRepository,
            mock(ProcessRepository.class),
            new CapturingJdbcTemplate(),
            mock(OperationLogService.class)
        );

        var preview = service.preview("process", workbookWithLegacyActiveProcessStatus());

        assertThat(preview.getSuccessCount()).isEqualTo(1);
        assertThat(preview.getFailCount()).isZero();
        assertThat(preview.getRows().get(0).getValues()).containsEntry("status", "confirmed");
    }

    @Test
    void processPreviewForcesImportedDraftStatusToConfirmed() throws Exception {
        ProductRepository productRepository = mock(ProductRepository.class);
        Product product = new Product();
        product.setProductId(100L);
        when(productRepository.selectOne(any())).thenReturn(product);
        MasterDataImportExportServiceImpl service = new MasterDataImportExportServiceImpl(
            productRepository,
            mock(ProcessRepository.class),
            new CapturingJdbcTemplate(),
            mock(OperationLogService.class)
        );

        var preview = service.preview("process", workbookWithProcessStatus("draft"));

        assertThat(preview.getSuccessCount()).isEqualTo(1);
        assertThat(preview.getFailCount()).isZero();
        assertThat(preview.getRows().get(0).getValues()).containsEntry("status", "confirmed");
    }

    @Test
    void processImportCreatesOneRoutePerLegacyProductGroupAndAttachesOperations() throws Exception {
        ProductRepository productRepository = mock(ProductRepository.class);
        Product product = new Product();
        product.setProductId(100L);
        product.setProductCode("PRD-HA");
        product.setProductName("Product HA");
        product.setProductType("product_line");
        product.setProductSpecificCode("HA");
        when(productRepository.selectOne(any())).thenReturn(
            null, null, product,
            null, null, product,
            null, null, product,
            null, null, product
        );
        ProcessRepository processRepository = mock(ProcessRepository.class);
        AtomicLong processIds = new AtomicLong(200L);
        when(processRepository.insert(any(ProcessEntity.class))).thenAnswer(invocation -> {
            ProcessEntity process = invocation.getArgument(0);
            process.setProcessId(processIds.incrementAndGet());
            return 1;
        });
        OperationLogService operationLogService = mock(OperationLogService.class);
        when(operationLogService.logSuccess(any())).thenReturn(1L);
        MasterDataImportExportServiceImpl service = new MasterDataImportExportServiceImpl(
            productRepository,
            processRepository,
            new CapturingJdbcTemplate(),
            operationLogService
        );

        var preview = service.preview("process", workbookWithLegacyOperationRouteRows());
        var committed = service.commit(preview.getImportToken(), null);

        assertThat(preview.getSuccessCount()).isEqualTo(2);
        assertThat(committed.getSuccessCount()).isEqualTo(2);
        assertThat(committed.getFailCount()).isZero();
        ArgumentCaptor<ProcessEntity> captor = ArgumentCaptor.forClass(ProcessEntity.class);
        verify(processRepository, times(3)).insert(captor.capture());
        List<ProcessEntity> inserted = captor.getAllValues();
        assertThat(inserted).extracting(ProcessEntity::getProcessType)
            .containsExactly("routing", "operation", "operation");
        ProcessEntity route = inserted.get(0);
        assertThat(route.getProductId()).isEqualTo(100L);
        assertThat(route.getProcessCode()).isEqualTo("ROUTE-PRD-HA-IMPORT-1");
        assertThat(route.getProcessName()).isEqualTo("Product HA 工艺路线");
        assertThat(route.getVersionNo()).isEqualTo("A");
        assertThat(route.getStatus()).isEqualTo("confirmed");

        ProcessEntity spray = inserted.get(1);
        ProcessEntity assembly = inserted.get(2);
        assertThat(spray.getParentProcessId()).isEqualTo(route.getProcessId());
        assertThat(spray.getProductId()).isEqualTo(100L);
        assertThat(spray.getStatus()).isEqualTo("confirmed");
        assertThat(spray.getOperationCraftCode()).isEqualTo("3020");
        assertThat(spray.getMaterialStatusCode()).isEqualTo("3020");
        assertThat(spray.getBusinessOperationCode()).isEqualTo("NHA3020");
        assertThat(spray.getFinishedProductFlag()).isFalse();
        assertThat(assembly.getParentProcessId()).isEqualTo(route.getProcessId());
        assertThat(assembly.getStatus()).isEqualTo("confirmed");
        assertThat(assembly.getOperationCraftCode()).isEqualTo("4030");
        assertThat(assembly.getMaterialStatusCode()).isEqualTo("4030");
        assertThat(assembly.getBusinessOperationCode()).isEqualTo("NHA4030");
        assertThat(assembly.getFinishedProductFlag()).isTrue();
    }

    @Test
    void processImportRelinksExistingLegacyOperationsWhenProcessCodesAlreadyExist() throws Exception {
        ProductRepository productRepository = mock(ProductRepository.class);
        Product product = new Product();
        product.setProductId(100L);
        product.setProductCode("PRD-HA");
        product.setProductName("Product HA");
        product.setProductType("product_line");
        product.setProductSpecificCode("HA");
        when(productRepository.selectOne(any())).thenReturn(
            null, null, product,
            null, null, product,
            null, null, product,
            null, null, product
        );
        ProcessEntity existingSpray = new ProcessEntity();
        existingSpray.setProcessId(301L);
        existingSpray.setProcessCode("PROC-NHA3020");
        existingSpray.setProcessType("operation");
        ProcessEntity existingAssembly = new ProcessEntity();
        existingAssembly.setProcessId(302L);
        existingAssembly.setProcessCode("PROC-NHA4030");
        existingAssembly.setProcessType("operation");
        ProcessRepository processRepository = mock(ProcessRepository.class);
        when(processRepository.selectOne(any())).thenReturn(null, existingSpray, existingAssembly);
        AtomicLong processIds = new AtomicLong(200L);
        when(processRepository.insert(any(ProcessEntity.class))).thenAnswer(invocation -> {
            ProcessEntity process = invocation.getArgument(0);
            process.setProcessId(processIds.incrementAndGet());
            return 1;
        });
        OperationLogService operationLogService = mock(OperationLogService.class);
        when(operationLogService.logSuccess(any())).thenReturn(1L);
        MasterDataImportExportServiceImpl service = new MasterDataImportExportServiceImpl(
            productRepository,
            processRepository,
            new CapturingJdbcTemplate(),
            operationLogService
        );

        var preview = service.preview("process", workbookWithLegacyOperationRouteRows());
        var committed = service.commit(preview.getImportToken(), null);

        assertThat(preview.getSuccessCount()).isEqualTo(2);
        assertThat(preview.getFailCount()).isZero();
        assertThat(committed.getSuccessCount()).isEqualTo(2);
        ArgumentCaptor<ProcessEntity> insertedCaptor = ArgumentCaptor.forClass(ProcessEntity.class);
        verify(processRepository, times(1)).insert(insertedCaptor.capture());
        ProcessEntity route = insertedCaptor.getValue();
        assertThat(route.getProcessType()).isEqualTo("routing");
        ArgumentCaptor<ProcessEntity> updatedCaptor = ArgumentCaptor.forClass(ProcessEntity.class);
        verify(processRepository, times(2)).updateById(updatedCaptor.capture());
        List<ProcessEntity> updated = updatedCaptor.getAllValues();
        assertThat(updated).extracting(ProcessEntity::getProcessId).containsExactly(301L, 302L);
        assertThat(updated).allSatisfy(operation -> {
            assertThat(operation.getParentProcessId()).isEqualTo(route.getProcessId());
            assertThat(operation.getProductId()).isEqualTo(100L);
        });
        assertThat(updated.get(0).getOperationCraftCode()).isEqualTo("3020");
        assertThat(updated.get(1).getOperationCraftCode()).isEqualTo("4030");
        assertThat(updated.get(1).getFinishedProductFlag()).isTrue();
    }

    @Test
    void inventoryPreviewAcceptsChineseTemplateHeaders() throws Exception {
        MasterDataImportExportServiceImpl service = new MasterDataImportExportServiceImpl(
            mock(ProductRepository.class),
            mock(ProcessRepository.class),
            new CapturingJdbcTemplate(),
            mock(OperationLogService.class)
        );

        var preview = service.preview("inventory", workbookWithChineseInventoryHeaders());

        assertThat(preview.getSuccessCount()).isEqualTo(1);
        assertThat(preview.getRows()).hasSize(1);
        assertThat(preview.getRows().get(0).getValues().get("inventory_code")).isEqualTo("INV-MAT-CN-001");
    }

    @Test
    void inventoryPreviewAcceptsScreenshotMaterialImportHeaders() throws Exception {
        MasterDataImportExportServiceImpl service = new MasterDataImportExportServiceImpl(
            mock(ProductRepository.class),
            mock(ProcessRepository.class),
            new CapturingJdbcTemplate(),
            mock(OperationLogService.class)
        );

        var preview = service.preview("inventory", workbookWithScreenshotInventoryHeaders());

        assertThat(preview.getSuccessCount()).isEqualTo(1);
        assertThat(preview.getFailCount()).isZero();
        var values = preview.getRows().get(0).getValues();
        assertThat(values).containsEntry("ecount_major_name", "工具");
        assertThat(values).containsEntry("inventory_code", "GJ000260");
        assertThat(values).containsEntry("inventory_name", "羊毛球");
        assertThat(values).containsEntry("specification", "柱形羊毛球/柄径3mm/D8mm/100个-包");
        assertThat(values).containsEntry("unit", "个");
        assertThat(values).containsEntry("source_created_date", "2020/2/20");
        assertThat(values).containsEntry("inventory_type", "tooling");
        assertThat(values).containsEntry("supplier_name", "默认供应商");
        assertThat(values).containsEntry("currency_code", "CNY");
        assertThat(values).containsEntry("status", "available");
        assertThat(values.get("remark")).contains("ECOUNT导入", "一级=工具", "新增日期=2020/2/20");
    }

    @Test
    void inventoryPreviewRebuildsCodeWhenConvertedTemplateUsesSequenceCode() throws Exception {
        MasterDataImportExportServiceImpl service = new MasterDataImportExportServiceImpl(
            mock(ProductRepository.class),
            mock(ProcessRepository.class),
            new CapturingJdbcTemplate(),
            mock(OperationLogService.class)
        );

        var preview = service.preview("inventory", workbookWithConvertedInventorySequenceCode());

        assertThat(preview.getSuccessCount()).isEqualTo(1);
        assertThat(preview.getRows()).hasSize(1);
        var values = preview.getRows().get(0).getValues();
        assertThat(values).containsEntry("ecount_major_code", "GL");
        assertThat(values).containsEntry("ecount_major_name", "金属材料");
        assertThat(values).containsEntry("inventory_code", "GL000008");
        assertThat(values).containsEntry("inventory_name", "RECTIFICADORA NEUMÁTICA 风动打磨机");
    }

    @Test
    void productPreviewDetectsShortAndFinishedBusinessCodes() throws Exception {
        MasterDataImportExportServiceImpl service = new MasterDataImportExportServiceImpl(
            mock(ProductRepository.class),
            mock(ProcessRepository.class),
            new CapturingJdbcTemplate(),
            mock(OperationLogService.class)
        );

        var preview = service.preview("product", workbookWithProductBusinessCodes());

        assertThat(preview.getSuccessCount()).isEqualTo(3);
        assertThat(preview.getRows()).hasSize(3);
        assertThat(preview.getRows().get(0).getValues()).containsEntry("normalized_code", "AB123");
        assertThat(preview.getRows().get(0).getValues()).containsEntry("detected_object_type", "product_short_code");
        assertThat(preview.getRows().get(0).getValues()).containsEntry("match_status", "create_candidate");
        assertThat(preview.getRows().get(1).getValues()).containsEntry("normalized_code", "NFA4030129101");
        assertThat(preview.getRows().get(1).getValues()).containsEntry("detected_object_type", "finished_product_code");
        assertThat(preview.getRows().get(1).getValues()).containsEntry("matched_finished_code", "NFA4030129101");
        assertThat(preview.getRows().get(2).getValues()).containsEntry("normalized_code", "LLT10");
        assertThat(preview.getRows().get(2).getValues()).containsEntry("detected_object_type", "mold_code");
        assertThat(preview.getRows().get(2).getValues()).containsEntry("match_message", "mold:LT/10/");
    }

    @Test
    void productPreviewDoesNotParseLegacyProductCodeAsBusinessCodeWhenImportCodesAreBlank() throws Exception {
        MasterDataImportExportServiceImpl service = new MasterDataImportExportServiceImpl(
            mock(ProductRepository.class),
            mock(ProcessRepository.class),
            new CapturingJdbcTemplate(),
            mock(OperationLogService.class)
        );

        var preview = service.preview("product", workbookWithLegacyProductCodeOnly());

        assertThat(preview.getSuccessCount()).isEqualTo(1);
        assertThat(preview.getFailCount()).isZero();
        assertThat(preview.getRows().get(0).getValues()).containsEntry("product_code", "NDN4030");
        assertThat(preview.getRows().get(0).getValues()).containsEntry("match_status", "");
    }

    @Test
    void productPreviewAcceptsLegacyXlsWorkbook() throws Exception {
        MasterDataImportExportServiceImpl service = new MasterDataImportExportServiceImpl(
            mock(ProductRepository.class),
            mock(ProcessRepository.class),
            new CapturingJdbcTemplate(),
            mock(OperationLogService.class)
        );

        var preview = service.preview("product", legacyXlsProductWorkbook());

        assertThat(preview.getSuccessCount()).isEqualTo(1);
        assertThat(preview.getFailCount()).isZero();
        assertThat(preview.getRows().get(0).getValues()).containsEntry("product_code", "PRD-XLS-001");
    }

    @Test
    void productPreviewAcceptsParentProductFromSameWorkbook() throws Exception {
        MasterDataImportExportServiceImpl service = new MasterDataImportExportServiceImpl(
            mock(ProductRepository.class),
            mock(ProcessRepository.class),
            new CapturingJdbcTemplate(),
            mock(OperationLogService.class)
        );

        var preview = service.preview("product", workbookWithParentAndVariantProducts());

        assertThat(preview.getSuccessCount()).isEqualTo(2);
        assertThat(preview.getFailCount()).isZero();
    }

    @Test
    void productPreviewRequiresParentProductForModelVariant() throws Exception {
        MasterDataImportExportServiceImpl service = new MasterDataImportExportServiceImpl(
            mock(ProductRepository.class),
            mock(ProcessRepository.class),
            new CapturingJdbcTemplate(),
            mock(OperationLogService.class)
        );

        var preview = service.preview("product", workbookWithModelVariantWithoutParent());

        assertThat(preview.getSuccessCount()).isZero();
        assertThat(preview.getFailCount()).isEqualTo(1);
        assertThat(preview.getErrors()).anySatisfy(error -> {
            assertThat(error.getFieldName()).isEqualTo("parent_product_code");
            assertThat(error.getErrorMessage()).contains("model_variant");
        });
    }

    @Test
    void productImportLinksSameWorkbookParentAndSetsArchivedRowsToTerminalStep() throws Exception {
        ProductRepository productRepository = mock(ProductRepository.class);
        AtomicLong productIds = new AtomicLong(1000L);
        when(productRepository.insert(any(Product.class))).thenAnswer(invocation -> {
            Product product = invocation.getArgument(0);
            product.setProductId(productIds.incrementAndGet());
            return 1;
        });
        OperationLogService operationLogService = mock(OperationLogService.class);
        when(operationLogService.logSuccess(any())).thenReturn(1L);
        MasterDataImportExportServiceImpl service = new MasterDataImportExportServiceImpl(
            productRepository,
            mock(ProcessRepository.class),
            new CapturingJdbcTemplate(),
            operationLogService
        );

        var preview = service.preview("product", workbookWithParentAndVariantProducts());
        service.commit(preview.getImportToken(), null);

        ArgumentCaptor<Product> captor = ArgumentCaptor.forClass(Product.class);
        verify(productRepository, times(2)).insert(captor.capture());
        Product parent = captor.getAllValues().get(0);
        Product variant = captor.getAllValues().get(1);
        assertThat(parent.getProductCode()).isEqualTo("NDN4030");
        assertThat(parent.getCurrentStepNo()).isEqualTo(22);
        assertThat(variant.getProductCode()).isEqualTo("NDN4030000031");
        assertThat(variant.getParentProductId()).isEqualTo(parent.getProductId());
        assertThat(variant.getCurrentStepNo()).isEqualTo(18);
    }

    @Test
    void inventoryPreviewAcceptsEcountCompositeHeadersAndDerivesInventoryFields() throws Exception {
        MasterDataImportExportServiceImpl service = new MasterDataImportExportServiceImpl(
            mock(ProductRepository.class),
            mock(ProcessRepository.class),
            new CapturingJdbcTemplate(),
            mock(OperationLogService.class)
        );

        var preview = service.preview("inventory", workbookWithEcountInventoryRows(
            new String[] {"1", "YL", "原料", "000001", "原料TPU", "YL000001", "YL000001", "原料TPU", "HF-1190AL-3/25Kg-袋", "个 PIEZA", "#N/A", "2020/2/13", ""}
        ));

        assertThat(preview.getSuccessCount()).isEqualTo(1);
        assertThat(preview.getFailCount()).isZero();
        var values = preview.getRows().get(0).getValues();
        assertThat(values.get("inventory_code")).isEqualTo("YL000001");
        assertThat(values.get("inventory_name")).isEqualTo("原料TPU");
        assertThat(values.get("inventory_type")).isEqualTo("material");
        assertThat(values.get("unit")).isEqualTo("个");
        assertThat(values.get("supplier_name")).isEqualTo("默认供应商");
        assertThat(values.get("currency_code")).isEqualTo("CNY");
        assertThat(values.get("status")).isEqualTo("available");
        assertThat(values.get("remark")).contains("ECOUNT导入", "一级=YL/原料", "二级=000001/原料TPU", "新增日期=2020/2/13");
    }

    @Test
    void inventoryPreviewNormalizesLegacyZeroAuxiliaryGroupToFlCode() throws Exception {
        MasterDataImportExportServiceImpl service = new MasterDataImportExportServiceImpl(
            mock(ProductRepository.class),
            mock(ProcessRepository.class),
            new CapturingJdbcTemplate(),
            mock(OperationLogService.class)
        );

        var preview = service.preview("inventory", workbookWithEcountInventoryRows(
            new String[] {"", "0", "\u8f85\u6599", "000568", "\u51b0\u76fe\u7247\u6750", "", "0000568", "\u51b0\u76fe\u7247\u6750", "PC/\u900f\u660e\u767d\u5e95/T1.5mm/Xiaomi Mi 11 Lite 4G/5G", "\u7247 PIEZA", "", "2021/10/27", ""}
        ));

        assertThat(preview.getSuccessCount()).isEqualTo(1);
        var values = preview.getRows().get(0).getValues();
        assertThat(values).containsEntry("ecount_major_code", "FL");
        assertThat(values).containsEntry("ecount_major_name", "\u8f85\u6599");
        assertThat(values).containsEntry("ecount_minor_code", "000568");
        assertThat(values).containsEntry("inventory_code", "FL000568");
        assertThat(values).containsEntry("inventory_name", "\u51b0\u76fe\u7247\u6750");
        assertThat(values).containsEntry("unit", "\u7247");
    }

    @Test
    void inventoryPreviewReportsDuplicateEcountMaterialCodes() throws Exception {
        MasterDataImportExportServiceImpl service = new MasterDataImportExportServiceImpl(
            mock(ProductRepository.class),
            mock(ProcessRepository.class),
            new CapturingJdbcTemplate(),
            mock(OperationLogService.class)
        );

        var preview = service.preview("inventory", workbookWithEcountInventoryRows(
            new String[] {"1", "FL", "辅料", "000001", "包装盒", "FL000001", "FL000001", "包装盒", "透明", "个", "", "2024/1/1", ""},
            new String[] {"2", "FL", "辅料", "000002", "包装盒", "FL000002", "FL000001", "包装盒", "磨砂", "个", "", "2024/1/2", ""}
        ));

        assertThat(preview.getSuccessCount()).isEqualTo(1);
        assertThat(preview.getFailCount()).isEqualTo(1);
        assertThat(preview.getErrors()).anySatisfy(error -> {
            assertThat(error.getFieldName()).isEqualTo("inventory_code");
            assertThat(error.getRawValue()).isEqualTo("FL000001");
        });
    }

    @Test
    void inventoryImportUsesDefaultSupplierWhenSupplierNameIsBlank() throws Exception {
        CapturingJdbcTemplate jdbcTemplate = new CapturingJdbcTemplate();
        OperationLogService operationLogService = mock(OperationLogService.class);
        when(operationLogService.logSuccess(any())).thenReturn(1L);
        MasterDataImportExportServiceImpl service = new MasterDataImportExportServiceImpl(
            mock(ProductRepository.class),
            mock(ProcessRepository.class),
            jdbcTemplate,
            operationLogService
        );

        var preview = service.preview("inventory", workbookWithInventorySupplier(""));
        service.commit(preview.getImportToken(), null);

        assertThat(jdbcTemplate.insertedSupplierName).isEqualTo("默认供应商");
    }

    @Test
    void commitReturnsResultWhenOperationLogFails() throws Exception {
        CapturingJdbcTemplate jdbcTemplate = new CapturingJdbcTemplate();
        OperationLogService operationLogService = mock(OperationLogService.class);
        doThrow(new IllegalStateException("operation log unavailable")).when(operationLogService).logSuccess(any());
        MasterDataImportExportServiceImpl service = new MasterDataImportExportServiceImpl(
            mock(ProductRepository.class),
            mock(ProcessRepository.class),
            jdbcTemplate,
            operationLogService
        );

        var preview = service.preview("inventory", workbookWithInventorySupplier(""));
        var committed = service.commit(preview.getImportToken(), null);

        assertThat(committed.getSuccessCount()).isEqualTo(1);
        assertThat(jdbcTemplate.insertedSupplierName).isEqualTo("默认供应商");
    }

    @Test
    void inventoryImportLinksEcountMaterialGroupWhenDictionaryExists() throws Exception {
        MaterialGroupJdbcTemplate jdbcTemplate = new MaterialGroupJdbcTemplate();
        OperationLogService operationLogService = mock(OperationLogService.class);
        when(operationLogService.logSuccess(any())).thenReturn(1L);
        MasterDataImportExportServiceImpl service = new MasterDataImportExportServiceImpl(
            mock(ProductRepository.class),
            mock(ProcessRepository.class),
            jdbcTemplate,
            operationLogService
        );

        var preview = service.preview("inventory", workbookWithEcountInventoryRows(
            new String[] {"1", "YL", "原料", "000001", "原料TPU", "YL000001", "YL000001", "原料TPU", "HF-1190AL", "kg", "", "2020/2/13", ""}
        ));
        service.commit(preview.getImportToken(), null);

        assertThat(jdbcTemplate.requestedMaterialGroupKey).isEqualTo("L1:YL:原料");
        assertThat(jdbcTemplate.insertedMaterialGroupId).isEqualTo(1L);
    }

    @Test
    void batchesReturnsEmptyWhenImportBatchTableIsMissing() {
        MasterDataImportExportServiceImpl service = new MasterDataImportExportServiceImpl(
            mock(ProductRepository.class),
            mock(ProcessRepository.class),
            new MissingImportBatchTableJdbcTemplate(),
            mock(OperationLogService.class)
        );

        assertThat(service.batches("inventory")).isEmpty();
    }

    @Test
    void commitImportsInventoryWhenImportBatchTableIsMissing() throws Exception {
        MissingImportBatchTableOnCommitJdbcTemplate jdbcTemplate = new MissingImportBatchTableOnCommitJdbcTemplate();
        OperationLogService operationLogService = mock(OperationLogService.class);
        when(operationLogService.logSuccess(any())).thenReturn(1L);
        MasterDataImportExportServiceImpl service = new MasterDataImportExportServiceImpl(
            mock(ProductRepository.class),
            mock(ProcessRepository.class),
            jdbcTemplate,
            operationLogService
        );

        var preview = service.preview("inventory", workbookWithInventorySupplier(""));
        var committed = service.commit(preview.getImportToken(), null);

        assertThat(committed.getSuccessCount()).isEqualTo(1);
        assertThat(jdbcTemplate.insertedSupplierName).isEqualTo("默认供应商");
    }

    @Test
    void commitImportsInventoryWhenImportBatchMetadataSchemaIsIncompatible() throws Exception {
        IncompatibleImportBatchMetadataJdbcTemplate jdbcTemplate = new IncompatibleImportBatchMetadataJdbcTemplate();
        OperationLogService operationLogService = mock(OperationLogService.class);
        when(operationLogService.logSuccess(any())).thenReturn(1L);
        MasterDataImportExportServiceImpl service = new MasterDataImportExportServiceImpl(
            mock(ProductRepository.class),
            mock(ProcessRepository.class),
            jdbcTemplate,
            operationLogService
        );

        var preview = service.preview("inventory", workbookWithInventorySupplier(""));
        var committed = service.commit(preview.getImportToken(), null);

        assertThat(committed.getSuccessCount()).isEqualTo(1);
        assertThat(jdbcTemplate.insertedSupplierName).isEqualTo("默认供应商");
    }

    private static BadSqlGrammarException missingImportBatchTable(String sql) {
        return new BadSqlGrammarException(
            "query",
            sql,
            new SQLException("relation \"plm_import_batch\" does not exist", "42P01")
        );
    }

    private MockMultipartFile workbookWithInventorySupplier(String supplierName) throws Exception {
        try (XSSFWorkbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            var sheet = workbook.createSheet("inventory");
            var header = sheet.createRow(0);
            String[] headers = {
                "inventory_code", "inventory_name", "inventory_type", "specification", "unit",
                "supplier_name", "unit_cost", "currency_code", "status", "remark"
            };
            for (int index = 0; index < headers.length; index++) {
                header.createCell(index).setCellValue(headers[index]);
            }

            var row = sheet.createRow(1);
            String[] values = {
                "INV-MAT-DEFAULT-SUP", "TPU 85A", "material", "85A", "kg",
                supplierName, "25.5", "CNY", "available", "history"
            };
            for (int index = 0; index < values.length; index++) {
                row.createCell(index).setCellValue(values[index]);
            }
            workbook.write(output);
            return new MockMultipartFile(
                "file",
                "inventory.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                output.toByteArray()
            );
        }
    }

    private MockMultipartFile legacyXlsProductWorkbook() throws Exception {
        try (HSSFWorkbook workbook = new HSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            var sheet = workbook.createSheet("product_template");
            var header = sheet.createRow(0);
            String[] headers = {
                "product_code", "product_name", "product_type", "version_no", "status"
            };
            for (int index = 0; index < headers.length; index++) {
                header.createCell(index).setCellValue(headers[index]);
            }

            var row = sheet.createRow(1);
            String[] values = {
                "PRD-XLS-001", "旧版 XLS 产品", "product_line", "A", "archived"
            };
            for (int index = 0; index < values.length; index++) {
                row.createCell(index).setCellValue(values[index]);
            }
            workbook.write(output);
            return new MockMultipartFile(
                "file",
                "product.xls",
                "application/vnd.ms-excel",
                output.toByteArray()
            );
        }
    }

    private MockMultipartFile workbookWithChineseProcessHeaders() throws Exception {
        try (XSSFWorkbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            var sheet = workbook.createSheet("process");
            var header = sheet.createRow(0);
            String[] headers = {
                "product_code", "工艺编码", "工艺名称", "工艺类型", "父级工艺编码",
                "顺序号", "版本号", "状态", "质量要求", "备注"
            };
            for (int index = 0; index < headers.length; index++) {
                header.createCell(index).setCellValue(headers[index]);
            }

            var row = sheet.createRow(1);
            String[] values = {
                "PRD-CN-001", "PROC-CN-001", "喷油", "operation", "",
                "10", "A", "archived", "外观无色差", "中文工艺模板"
            };
            for (int index = 0; index < values.length; index++) {
                row.createCell(index).setCellValue(values[index]);
            }
            workbook.write(output);
            return new MockMultipartFile(
                "file",
                "process-cn.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                output.toByteArray()
            );
        }
    }

    private MockMultipartFile workbookWithNotesBeforeProcessTemplate() throws Exception {
        try (XSSFWorkbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            var notes = workbook.createSheet("conversion_notes");
            notes.createRow(0).createCell(0).setCellValue("scope");
            notes.getRow(0).createCell(1).setCellValue("key");
            notes.getRow(0).createCell(2).setCellValue("note");
            notes.createRow(1).createCell(0).setCellValue("process_import");

            var sheet = workbook.createSheet("process_template");
            var header = sheet.createRow(0);
            String[] headers = {
                "product_code", "process_code", "process_name", "process_type", "parent_process_code",
                "sequence_no", "version_no", "status", "quality_requirement", "remark"
            };
            for (int index = 0; index < headers.length; index++) {
                header.createCell(index).setCellValue(headers[index]);
            }

            var row = sheet.createRow(1);
            String[] values = {
                "PRD-NOTES-001", "PROC-NOTES-001", "Notes route", "routing", "",
                "1", "V1", "confirmed", "", "template sheet is not the first workbook sheet"
            };
            for (int index = 0; index < values.length; index++) {
                row.createCell(index).setCellValue(values[index]);
            }
            workbook.write(output);
            return new MockMultipartFile(
                "file",
                "process-with-notes-first.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                output.toByteArray()
            );
        }
    }

    private MockMultipartFile workbookWithBlankRowBeforeProcessHeaders() throws Exception {
        try (XSSFWorkbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            var sheet = workbook.createSheet("process_template");
            sheet.createRow(0).createCell(0).setCellValue("");
            var header = sheet.createRow(1);
            String[] headers = {
                "product_code", "process_code", "process_name", "process_type", "parent_process_code",
                "sequence_no", "version_no", "status", "quality_requirement", "remark"
            };
            for (int index = 0; index < headers.length; index++) {
                header.createCell(index).setCellValue(headers[index]);
            }

            var row = sheet.createRow(2);
            String[] values = {
                "PRD-SCAN-001", "PROC-SCAN-001", "Scanned route", "routing", "",
                "1", "V1", "confirmed", "", "header row is not the first sheet row"
            };
            for (int index = 0; index < values.length; index++) {
                row.createCell(index).setCellValue(values[index]);
            }
            workbook.write(output);
            return new MockMultipartFile(
                "file",
                "process-with-offset-header.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                output.toByteArray()
            );
        }
    }

    private MockMultipartFile workbookWithLegacyActiveProcessStatus() throws Exception {
        return workbookWithProcessStatus("active");
    }

    private MockMultipartFile workbookWithProcessStatus(String status) throws Exception {
        try (XSSFWorkbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            var sheet = workbook.createSheet("process_template");
            var header = sheet.createRow(0);
            String[] headers = {
                "product_code", "process_code", "process_name", "process_type", "parent_process_code",
                "sequence_no", "version_no", "status", "quality_requirement", "remark"
            };
            for (int index = 0; index < headers.length; index++) {
                header.createCell(index).setCellValue(headers[index]);
            }

            var row = sheet.createRow(1);
            String[] values = {
                "PRD-ACTIVE-001", "PROC-ACTIVE-001", "Legacy active operation", "operation", "",
                "10", "A", status, "", "legacy status from converted process workbook"
            };
            for (int index = 0; index < values.length; index++) {
                row.createCell(index).setCellValue(values[index]);
            }
            workbook.write(output);
            return new MockMultipartFile(
                "file",
                "process-" + status + "-status.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                output.toByteArray()
            );
        }
    }

    private MockMultipartFile workbookWithLegacyOperationRouteRows() throws Exception {
        try (XSSFWorkbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            var sheet = workbook.createSheet("process_template");
            var header = sheet.createRow(0);
            String[] headers = {
                "product_code", "process_code", "process_name", "process_type", "parent_process_code",
                "sequence_no", "version_no", "status", "quality_requirement", "remark"
            };
            for (int index = 0; index < headers.length; index++) {
                header.createCell(index).setCellValue(headers[index]);
            }
            String[][] rows = {
                {"NHA3020", "PROC-NHA3020", "Spray PC", "operation", "", "20", "A", "active", "appearance ok", "legacy process route"},
                {"NHA4030", "PROC-NHA4030", "Assembly", "operation", "", "30", "A", "active", "appearance ok", "legacy process route"}
            };
            for (int rowIndex = 0; rowIndex < rows.length; rowIndex++) {
                var row = sheet.createRow(rowIndex + 1);
                for (int columnIndex = 0; columnIndex < rows[rowIndex].length; columnIndex++) {
                    row.createCell(columnIndex).setCellValue(rows[rowIndex][columnIndex]);
                }
            }
            workbook.write(output);
            return new MockMultipartFile(
                "file",
                "legacy-process-route.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                output.toByteArray()
            );
        }
    }

    private MockMultipartFile workbookWithProductBusinessCodes() throws Exception {
        try (XSSFWorkbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            var sheet = workbook.createSheet("product");
            var header = sheet.createRow(0);
            String[] headers = {
                "product_code", "product_name", "product_type", "parent_product_code", "series_name", "model", "color",
                "version_no", "status", "current_stage", "remark", "import_short_code", "finished_product_code"
            };
            for (int index = 0; index < headers.length; index++) {
                header.createCell(index).setCellValue(headers[index]);
            }
            String[][] rows = {
                {"PRD-AB123", "Product line", "product_line", "", "Series", "", "", "A", "draft", "", "", "ab123", ""},
                {"PRD-FA-1291-01", "iPhone 1291 black", "model_variant", "PRD-AB123", "Series", "iPhone 1291", "01", "A", "draft", "", "", "", "nfa4030129101"},
                {"PRD-LLT10", "Mold code line", "product_line", "", "Mold", "", "", "A", "draft", "", "", "llt10", ""}
            };
            for (int rowIndex = 0; rowIndex < rows.length; rowIndex++) {
                var row = sheet.createRow(rowIndex + 1);
                for (int columnIndex = 0; columnIndex < rows[rowIndex].length; columnIndex++) {
                    row.createCell(columnIndex).setCellValue(rows[rowIndex][columnIndex]);
                }
            }
            workbook.write(output);
            return new MockMultipartFile(
                "file",
                "product-business-codes.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                output.toByteArray()
            );
        }
    }

    private MockMultipartFile workbookWithLegacyProductCodeOnly() throws Exception {
        try (XSSFWorkbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            var sheet = workbook.createSheet("product");
            var header = sheet.createRow(0);
            String[] headers = {
                "product_code", "product_name", "product_type", "parent_product_code", "series_name", "model", "color",
                "version_no", "status", "current_stage", "remark", "import_short_code", "finished_product_code"
            };
            for (int index = 0; index < headers.length; index++) {
                header.createCell(index).setCellValue(headers[index]);
            }
            var row = sheet.createRow(1);
            String[] values = {
                "NDN4030", "Legacy product", "product_line", "", "Legacy", "", "",
                "V1", "archived", "seed import", "", "", ""
            };
            for (int index = 0; index < values.length; index++) {
                row.createCell(index).setCellValue(values[index]);
            }
            workbook.write(output);
            return new MockMultipartFile(
                "file",
                "legacy-product-code.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                output.toByteArray()
            );
        }
    }

    private MockMultipartFile workbookWithParentAndVariantProducts() throws Exception {
        try (XSSFWorkbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            var sheet = workbook.createSheet("product");
            var header = sheet.createRow(0);
            String[] headers = {
                "product_code", "product_name", "product_type", "parent_product_code", "series_name", "model", "color",
                "version_no", "status", "current_stage", "remark"
            };
            for (int index = 0; index < headers.length; index++) {
                header.createCell(index).setCellValue(headers[index]);
            }
            String[][] rows = {
                {"NDN4030", "Legacy line", "product_line", "", "Legacy", "", "", "V1", "archived", "seed import", ""},
                {"NDN4030000031", "Legacy variant", "model_variant", "NDN4030", "Legacy", "", "", "V1", "archived", "seed import", ""}
            };
            for (int rowIndex = 0; rowIndex < rows.length; rowIndex++) {
                var row = sheet.createRow(rowIndex + 1);
                for (int columnIndex = 0; columnIndex < rows[rowIndex].length; columnIndex++) {
                    row.createCell(columnIndex).setCellValue(rows[rowIndex][columnIndex]);
                }
            }
            workbook.write(output);
            return new MockMultipartFile(
                "file",
                "parent-and-variant-products.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                output.toByteArray()
            );
        }
    }

    private MockMultipartFile workbookWithModelVariantWithoutParent() throws Exception {
        try (XSSFWorkbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            var sheet = workbook.createSheet("product");
            var header = sheet.createRow(0);
            String[] headers = {
                "product_code", "product_name", "product_type", "parent_product_code", "series_name", "model", "color",
                "version_no", "status", "current_stage", "remark"
            };
            for (int index = 0; index < headers.length; index++) {
                header.createCell(index).setCellValue(headers[index]);
            }
            var row = sheet.createRow(1);
            String[] values = {
                "NDN4030000099", "Legacy variant without parent", "model_variant", "", "Legacy", "iPhone18", "black",
                "V1", "archived", "seed import", ""
            };
            for (int index = 0; index < values.length; index++) {
                row.createCell(index).setCellValue(values[index]);
            }
            workbook.write(output);
            return new MockMultipartFile(
                "file",
                "model-variant-without-parent.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                output.toByteArray()
            );
        }
    }

    private MockMultipartFile workbookWithEcountInventoryRows(String[]... rows) throws Exception {
        try (XSSFWorkbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            var sheet = workbook.createSheet("物料编码表");
            sheet.createRow(0).createCell(0).setCellValue("物料编码明细表");
            var header = sheet.createRow(1);
            String[] headerValues = {
                "序号", "一级", "", "二级", "", "旧编码", "新物料编码", "物料名称", "规格型号", "基本单位", "条形码", "新增日期", "备注"
            };
            for (int index = 0; index < headerValues.length; index++) {
                header.createCell(index).setCellValue(headerValues[index]);
            }
            var subHeader = sheet.createRow(2);
            String[] subHeaderValues = {
                "", "大类编码", "名　称", "流水编码", "名　称", "", "", "", "", "", "", "", ""
            };
            for (int index = 0; index < subHeaderValues.length; index++) {
                subHeader.createCell(index).setCellValue(subHeaderValues[index]);
            }
            sheet.createRow(3).createCell(13).setCellValue("良好");
            for (int rowIndex = 0; rowIndex < rows.length; rowIndex++) {
                var row = sheet.createRow(4 + rowIndex);
                for (int columnIndex = 0; columnIndex < rows[rowIndex].length; columnIndex++) {
                    row.createCell(columnIndex).setCellValue(rows[rowIndex][columnIndex]);
                }
            }
            workbook.write(output);
            return new MockMultipartFile(
                "file",
                "ecount-inventory.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                output.toByteArray()
            );
        }
    }

    private MockMultipartFile workbookWithChineseInventoryHeaders() throws Exception {
        try (XSSFWorkbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            var sheet = workbook.createSheet("inventory");
            var header = sheet.createRow(0);
            String[] headers = {
                "物料编码", "物料名称", "物料类型", "规格型号", "单位",
                "供应商名称", "单价", "币种", "状态", "备注"
            };
            for (int index = 0; index < headers.length; index++) {
                header.createCell(index).setCellValue(headers[index]);
            }

            var row = sheet.createRow(1);
            String[] values = {
                "INV-MAT-CN-001", "TPU 85A", "material", "85A", "kg",
                "", "25.5", "CNY", "available", "中文模板"
            };
            for (int index = 0; index < values.length; index++) {
                row.createCell(index).setCellValue(values[index]);
            }
            workbook.write(output);
            return new MockMultipartFile(
                "file",
                "inventory-cn.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                output.toByteArray()
            );
        }
    }

    private MockMultipartFile workbookWithScreenshotInventoryHeaders() throws Exception {
        try (XSSFWorkbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            var sheet = workbook.createSheet("inventory_template");
            var header = sheet.createRow(0);
            String[] headers = {
                "物料组", "物料编码", "物料名称", "规格型号", "规格", "新增日期"
            };
            for (int index = 0; index < headers.length; index++) {
                header.createCell(index).setCellValue(headers[index]);
            }

            var row = sheet.createRow(1);
            String[] values = {
                "工具", "GJ000260", "羊毛球", "柱形羊毛球/柄径3mm/D8mm/100个-包", "个", "2020/2/20"
            };
            for (int index = 0; index < values.length; index++) {
                row.createCell(index).setCellValue(values[index]);
            }
            workbook.write(output);
            return new MockMultipartFile(
                "file",
                "inventory-material-template.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                output.toByteArray()
            );
        }
    }

    private MockMultipartFile workbookWithConvertedInventorySequenceCode() throws Exception {
        try (XSSFWorkbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            var sheet = workbook.createSheet("inventory_template");
            var header = sheet.createRow(0);
            String[] headers = {
                "物料组", "物料编码", "物料名称", "规格型号", "规格", "新增日期"
            };
            for (int index = 0; index < headers.length; index++) {
                header.createCell(index).setCellValue(headers[index]);
            }

            var row = sheet.createRow(1);
            String[] values = {
                "GL 金属材料", "000008", "RECTIFICADORA NEUMÁTICA 风动打磨机", "", "台", "2020/2/20"
            };
            for (int index = 0; index < values.length; index++) {
                row.createCell(index).setCellValue(values[index]);
            }
            workbook.write(output);
            return new MockMultipartFile(
                "file",
                "inventory-sequence-code.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                output.toByteArray()
            );
        }
    }

    private static class CapturingJdbcTemplate extends JdbcTemplate {
        String insertedSupplierName;
        Long insertedMaterialGroupId;

        @Override
        public <T> T queryForObject(String sql, Class<T> requiredType) {
            return requiredType.cast(0);
        }

        @Override
        public <T> T queryForObject(String sql, Class<T> requiredType, Object... args) {
            return requiredType.cast(0);
        }

        @Override
        public int update(PreparedStatementCreator psc, KeyHolder generatedKeyHolder) {
            generatedKeyHolder.getKeyList().add(Map.<String, Object>of("import_batch_id", 1L));
            return 1;
        }

        @Override
        public int update(String sql, Object... args) {
            if (sql.contains("insert into plm_inventory")) {
                insertedSupplierName = (String) args[5];
                if (sql.contains("material_group_id")) {
                    insertedMaterialGroupId = (Long) args[10];
                }
            }
            return 1;
        }
    }

    private static final class MaterialGroupJdbcTemplate extends CapturingJdbcTemplate {
        String requestedMaterialGroupKey;

        @Override
        public <T> T queryForObject(String sql, Class<T> requiredType) {
            if (sql.contains("information_schema.tables") && sql.contains("plm_material_group")) {
                return requiredType.cast(1);
            }
            if (sql.contains("information_schema.columns") && sql.contains("material_group_id")) {
                return requiredType.cast(1);
            }
            return super.queryForObject(sql, requiredType);
        }

        @Override
        public <T> T queryForObject(String sql, Class<T> requiredType, Object... args) {
            if (sql.contains("information_schema.tables") && sql.contains("plm_material_group")) {
                return requiredType.cast(1);
            }
            if (sql.contains("information_schema.columns") && sql.contains("material_group_id")) {
                return requiredType.cast(1);
            }
            if (sql.contains("from plm_material_group")) {
                requestedMaterialGroupKey = (String) args[0];
                return requiredType.cast(1L);
            }
            return super.queryForObject(sql, requiredType, args);
        }
    }

    private static final class MissingImportBatchTableJdbcTemplate extends JdbcTemplate {
        @Override
        public <T> List<T> query(String sql, RowMapper<T> rowMapper, Object... args) {
            throw missingImportBatchTable(sql);
        }
    }

    private static final class MissingImportBatchTableOnCommitJdbcTemplate extends CapturingJdbcTemplate {
        @Override
        public int update(PreparedStatementCreator psc, KeyHolder generatedKeyHolder) {
            throw missingImportBatchTable("insert into plm_import_batch");
        }
    }

    private static final class IncompatibleImportBatchMetadataJdbcTemplate extends CapturingJdbcTemplate {
        @Override
        public int update(PreparedStatementCreator psc, KeyHolder generatedKeyHolder) {
            throw new BadSqlGrammarException(
                "insert",
                "insert into plm_import_batch (..., remark, ...)",
                new SQLException("column \"remark\" of relation \"plm_import_batch\" does not exist", "42703")
            );
        }
    }
}
