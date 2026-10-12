package com.yuewei.plm.module.bom.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.module.bom.dto.BomRouteSaveDTO;
import com.yuewei.plm.module.bom.dto.ProductBomItemDTO;
import com.yuewei.plm.module.bom.entity.ProductBom;
import com.yuewei.plm.module.bom.entity.ProductBomItem;
import com.yuewei.plm.module.bom.entity.ProductBomImportBatch;
import com.yuewei.plm.module.bom.entity.ProductBomRoute;
import com.yuewei.plm.module.bom.entity.ProductBomRouteColor;
import com.yuewei.plm.module.bom.repository.ProductBomImportBatchRepository;
import com.yuewei.plm.module.bom.repository.ProductBomItemRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteColorRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteRepository;
import com.yuewei.plm.module.bom.service.BomMaterialLookup;
import com.yuewei.plm.module.bom.service.BomAmountPolicy;
import com.yuewei.plm.module.pilot.PilotAccessService;
import com.yuewei.plm.module.bom.service.BomProcessRouteLookup;
import com.yuewei.plm.module.bom.service.ProductBomWorkflowService;
import com.yuewei.plm.module.bom.vo.BomImportErrorVO;
import com.yuewei.plm.module.bom.vo.BomImportPreviewVO;
import com.yuewei.plm.module.bom.vo.BomImportRowVO;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import com.yuewei.plm.module.code.entity.CodeItem;
import com.yuewei.plm.module.code.repository.CodeItemRepository;
import com.yuewei.plm.module.bom.dto.BomRouteColorDTO;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import lombok.RequiredArgsConstructor;
import org.apache.poi.ss.usermodel.DataFormatter;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class HistoricalBomImportService {
    private static final String PLACEHOLDER = "--";
    private static final String ERP_PLACEHOLDER_SOURCE = "erp_archive_placeholder";
    private static final List<String> HEADERS = List.of(
        "产品编码", "BOM版本", "行号", "路线编码", "路线名称", "适用颜色", "物料编码", "物料名称",
        "规格", "单位", "用量", "供应商", "单价", "单个成本", "损耗率", "替代料标识", "备注"
    );
    private static final List<String> ERP_OVERVIEW_HEADERS = List.of(
        "Código BOM", "Código padre", "Nombre padre", "Componentes", "SKUs asociados", "Estado", "Especificación", "Origen"
    );

    private final ProductBomImportBatchRepository batchRepository;
    private final ProductBomRepository bomRepository;
    private final ProductBomRouteRepository routeRepository;
    private final ProductBomRouteColorRepository routeColorRepository;
    private final ProductBomItemRepository itemRepository;
    private final ProductRepository productRepository;
    private final BomMaterialLookup materialLookup;
    private final BomProcessRouteLookup routeLookup;
    private final ProductBomWorkflowService workflowService;
    private final CodeItemRepository codeItemRepository;
    private final PilotAccessService access;
    private final ObjectMapper objectMapper = new ObjectMapper().findAndRegisterModules();

    public BomImportPreviewVO preview(String fileName, byte[] content) {
        access.requirePermission("bom:write");
        if (fileName == null || !fileName.toLowerCase().endsWith(".xlsx")) {
            throw validation("仅支持 xlsx 文件");
        }
        List<BomImportRowVO> rows = new ArrayList<>();
        List<BomImportErrorVO> errors = new ArrayList<>();
        try (XSSFWorkbook workbook = new XSSFWorkbook(new ByteArrayInputStream(content))) {
            var sheet = workbook.getNumberOfSheets() == 0 ? null : workbook.getSheetAt(0);
            if (sheet == null) {
                errors.add(new BomImportErrorVO(1, "表头", "", "未找到可解析的工作表"));
            } else {
                DataFormatter formatter = new DataFormatter();
                int erpOverviewHeaderRow = erpOverviewHeaderRow(sheet, formatter);
                if (validHeader(sheet.getRow(0))) {
                    for (int rowIndex = 1; rowIndex <= sheet.getLastRowNum(); rowIndex++) {
                        Row row = sheet.getRow(rowIndex);
                        if (row == null || text(row, 0, formatter).isBlank()) continue;
                        if (!text(row, 12, formatter).isBlank() || !text(row, 13, formatter).isBlank()) access.requireFinanceWrite();
                        parseRow(rowIndex + 1, row, formatter, rows, errors);
                    }
                } else if (erpOverviewHeaderRow >= 0) {
                    for (int rowIndex = erpOverviewHeaderRow + 1; rowIndex <= sheet.getLastRowNum(); rowIndex++) {
                        Row row = sheet.getRow(rowIndex);
                        if (row == null || text(row, 0, formatter).isBlank()) continue;
                        parseErpOverviewRow(rowIndex + 1, row, formatter, rows, errors);
                    }
                } else {
                    errors.add(new BomImportErrorVO(1, "表头", "", "表头必须与历史 BOM 导入模板或 ERP BOM 总览格式一致"));
                }
            }
        } catch (BusinessException exception) {
            throw exception;
        } catch (Exception exception) {
            throw validation("XLSX 解析失败：" + exception.getMessage());
        }
        String status = errors.isEmpty() && !rows.isEmpty() ? "ready" : "invalid";
        ProductBomImportBatch batch = new ProductBomImportBatch();
        batch.setProductId(rows.isEmpty() ? 0L : rows.get(0).getProductId());
        batch.setImportToken(UUID.randomUUID().toString());
        batch.setBomScope("history");
        batch.setFileName(fileName);
        batch.setStatus(status);
        batch.setTotalRows(rows.size() + errors.size());
        batch.setValidRows(rows.size());
        batch.setErrorRows(errors.size());
        batch.setPreviewJson(writeJson(rows));
        batch.setErrorJson(writeJson(errors));
        batch.setExpiresAt(LocalDateTime.now().plusHours(2));
        fillCreate(batch);
        batchRepository.insert(batch);
        return BomImportPreviewVO.builder().importToken(batch.getImportToken()).status(status)
            .totalRows(batch.getTotalRows()).validRows(rows.size()).errorRows(errors.size())
            .rows(rows).errors(errors).build();
    }

    @Transactional
    public ProductBomImportBatch commit(String importToken) {
        access.requirePermission("bom:write");
        ProductBomImportBatch batch = batchRepository.selectOne(new LambdaQueryWrapper<ProductBomImportBatch>()
            .eq(ProductBomImportBatch::getImportToken, importToken).eq(ProductBomImportBatch::getBomScope, "history")
            .eq(ProductBomImportBatch::getDeletedFlag, 0));
        if (batch == null) throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "历史导入批次不存在");
        if (!"ready".equals(batch.getStatus()) || batch.getExpiresAt().isBefore(LocalDateTime.now())) {
            throw validation("历史导入批次不可提交或已过期");
        }
        List<BomImportRowVO> importedRows = readRows(batch.getPreviewJson());
        BomImportServiceImpl.requireMoneyWrite(importedRows, access);
        importedRows.stream().map(BomImportRowVO::getProductId).distinct().forEach(access::requireProduct);
        batch.setStatus("committing");
        if (batchRepository.update(batch, new LambdaQueryWrapper<ProductBomImportBatch>()
            .eq(ProductBomImportBatch::getProductBomImportBatchId, batch.getProductBomImportBatchId())
            .eq(ProductBomImportBatch::getStatus, "ready")) != 1) {
            throw new BusinessException(ErrorCodeConstants.CODE_CONFLICT, "历史导入批次已被提交");
        }
        Map<String, List<BomImportRowVO>> byBom = new LinkedHashMap<>();
        boolean erpOverview = importedRows.stream().anyMatch(row -> row.getBomCode() != null && !row.getBomCode().isBlank());
        importedRows.forEach(row -> byBom.computeIfAbsent(
            row.getProductId() + "|" + row.getVersionNo(), key -> new ArrayList<>()).add(row));
        for (List<BomImportRowVO> bomRows : byBom.values()) {
            if (erpOverview) {
                createErpArchiveBom(bomRows);
            } else {
                createReleasedBom(bomRows);
            }
        }
        batch.setStatus("committed");
        batch.setCommittedAt(LocalDateTime.now());
        batch.setCommittedBy(access.actor().username());
        batch.setUpdatedAt(batch.getCommittedAt());
        batch.setUpdatedBy(access.actor().username());
        batchRepository.updateById(batch);
        return batch;
    }

    public byte[] buildTemplate() {
        try (XSSFWorkbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            var sheet = workbook.createSheet("历史BOM导入");
            var row = sheet.createRow(0);
            for (int index = 0; index < HEADERS.size(); index++) row.createCell(index).setCellValue(HEADERS.get(index));
            workbook.write(output);
            return output.toByteArray();
        } catch (Exception exception) {
            throw new BusinessException(ErrorCodeConstants.INTERNAL_ERROR, "历史导入模板生成失败");
        }
    }

    private void parseRow(int sourceRowNo, Row row, DataFormatter formatter,
        List<BomImportRowVO> rows, List<BomImportErrorVO> errors) {
        String productCode = text(row, 0, formatter);
        List<Product> products = productRepository.selectList(new LambdaQueryWrapper<Product>()
            .eq(Product::getProductCode, productCode).eq(Product::getDeletedFlag, 0));
        if (products == null || products.isEmpty()) {
            errors.add(new BomImportErrorVO(sourceRowNo, "产品编码", productCode, "未找到产品"));
            return;
        }
        if (products.size() != 1) {
            errors.add(new BomImportErrorVO(sourceRowNo, "产品编码", productCode, "产品编码匹配到多个产品，已阻止导入"));
            return;
        }
        Product product = products.get(0);
        access.requireProduct(product.getProductId());
        String versionNo = text(row, 1, formatter).trim();
        String bomCode = "HIS-" + productCode + "-" + versionNo;
        List<ProductBom> conflicts = bomRepository.selectList(new LambdaQueryWrapper<ProductBom>()
            .eq(ProductBom::getDeletedFlag, 0)
            .and(wrapper -> wrapper.eq(ProductBom::getBomCode, bomCode)
                .or().eq(ProductBom::getProductId, product.getProductId()).eq(ProductBom::getVersionNo, versionNo)));
        if (conflicts != null && !conflicts.isEmpty()) {
            errors.add(new BomImportErrorVO(sourceRowNo, "BOM版本", versionNo, "产品版本或历史 BOM 编码已存在"));
            return;
        }
        String routeCode = text(row, 3, formatter);
        var route = routeLookup.findByCode(product.getProductId(), routeCode);
        if (route.isEmpty()) {
            errors.add(new BomImportErrorVO(sourceRowNo, "路线编码", routeCode, "产品下不存在该工艺路线"));
            return;
        }
        String materialCode = text(row, 6, formatter);
        var material = materialLookup.findByCode(materialCode);
        if (material.isEmpty()) {
            errors.add(new BomImportErrorVO(sourceRowNo, "物料编码", materialCode, "物料不存在"));
            return;
        }
        try {
            BomMaterialLookup.Material matched = material.get();
            String itemName = text(row, 7, formatter);
            String specification = text(row, 8, formatter);
            String unit = text(row, 9, formatter);
            String supplierName = text(row, 11, formatter);
            BigDecimal unitCost = decimalOrNull(text(row, 12, formatter));
            BigDecimal lineCost = decimalOrNull(text(row, 13, formatter));
            if (itemName.isBlank()) itemName = matched.inventoryName();
            if (specification.isBlank()) specification = matched.specification();
            if (unit.isBlank()) unit = matched.unit();
            if (supplierName.isBlank()) supplierName = matched.supplierName();
            if (unitCost == null && access.hasPermission("finance:write")) unitCost = matched.unitCost();
            BomImportRowVO value = new BomImportRowVO();
            value.setProductId(product.getProductId());
            value.setProductCode(productCode);
            value.setVersionNo(required(versionNo, "BOM版本"));
            value.setLineNo(Integer.valueOf(required(text(row, 2, formatter), "行号")));
            value.setProcessId(route.get().processId());
            value.setRouteCode(route.get().routeCode());
            value.setRouteName(route.get().routeName());
            List<String> colorCodes = Arrays.stream(required(text(row, 5, formatter), "适用颜色").split("[,，]"))
                .map(String::trim).filter(item -> !item.isBlank()).distinct().toList();
            List<BomRouteColorDTO> colorItems = colorCodes.stream().map(this::requireEnabledColor).toList();
            value.setColorItems(colorItems);
            value.setColors(colorItems.stream().map(BomRouteColorDTO::getCodeName).toList());
            value.setInventoryId(matched.inventoryId());
            value.setItemCode(materialCode);
            value.setItemName(required(itemName, "物料名称"));
            value.setSpecification(specification);
            value.setUnit(required(unit, "单位"));
            value.setQuantity(new BigDecimal(required(text(row, 10, formatter), "用量")));
            value.setSupplierName(supplierName);
            value.setUnitCost(unitCost);
            value.setLineCost(lineCost == null && unitCost != null ? value.getQuantity().multiply(unitCost) : lineCost);
            value.setLossRate(text(row, 14, formatter).isBlank() ? BigDecimal.ZERO : new BigDecimal(text(row, 14, formatter)));
            if (access.hasPermission("finance:write")) value.setCurrencyCode(matched.currencyCode() == null || matched.currencyCode().isBlank() ? "CNY" : matched.currencyCode());
            value.setMaterialSource("inventory");
            value.setUnmatchedFlag(0);
            value.setSubstituteFlag("1".equals(text(row, 15, formatter)) ? 1 : 0);
            value.setRemark(text(row, 16, formatter));
            if (value.getQuantity().compareTo(BigDecimal.ZERO) <= 0) throw new IllegalArgumentException("用量必须大于 0");
            if (value.getUnitCost() != null && value.getUnitCost().compareTo(BigDecimal.ZERO) < 0) throw new IllegalArgumentException("单价不能为负数");
            if (value.getLineCost() != null && value.getLineCost().compareTo(BigDecimal.ZERO) < 0) throw new IllegalArgumentException("单个成本不能为负数");
            rows.add(value);
        } catch (Exception exception) {
            errors.add(new BomImportErrorVO(sourceRowNo, "数据", "", exception.getMessage()));
        }
    }

    private void parseErpOverviewRow(int sourceRowNo, Row row, DataFormatter formatter,
        List<BomImportRowVO> rows, List<BomImportErrorVO> errors) {
        String bomCode = text(row, 0, formatter);
        String parentCode = text(row, 1, formatter);
        if (bomCode.isBlank() || parentCode.isBlank()) {
            errors.add(new BomImportErrorVO(sourceRowNo, "BOM总览", "", "BOM 编码和父级产品编码不能为空"));
            return;
        }
        List<Product> products = findProductsForErpParentCode(parentCode);
        if (products.isEmpty()) {
            errors.add(new BomImportErrorVO(sourceRowNo, "Código padre", parentCode, "未找到父级产品或产品线"));
            return;
        }
        if (products.size() != 1) {
            errors.add(new BomImportErrorVO(sourceRowNo, "Código padre", parentCode, "父级产品编码匹配到多个产品，已阻止导入"));
            return;
        }
        Product product = products.get(0);
        access.requireProduct(product.getProductId());
        List<ProductBom> conflicts = bomRepository.selectList(new LambdaQueryWrapper<ProductBom>()
            .eq(ProductBom::getDeletedFlag, 0)
            .and(wrapper -> wrapper.eq(ProductBom::getBomCode, bomCode)
                .or().eq(ProductBom::getProductId, product.getProductId()).eq(ProductBom::getVersionNo, bomCode)));
        if (conflicts != null && !conflicts.isEmpty()) {
            errors.add(new BomImportErrorVO(sourceRowNo, "Código BOM", bomCode, "ERP BOM 编码或产品历史版本已存在"));
            return;
        }
        BomImportRowVO value = new BomImportRowVO();
        value.setProductId(product.getProductId());
        value.setProductCode(product.getProductCode());
        value.setBomCode(bomCode);
        value.setSourceParentCode(parentCode);
        value.setSourceParentName(text(row, 2, formatter));
        value.setComponentCount(integerOrNull(text(row, 3, formatter)));
        value.setAssociatedSkuCount(integerOrNull(text(row, 4, formatter)));
        value.setSourceStatus(text(row, 5, formatter));
        value.setSpecification(blankToDefault(text(row, 6, formatter), PLACEHOLDER));
        value.setSourceOrigin(blankToDefault(text(row, 7, formatter), "erp"));
        value.setVersionNo(bomCode);
        value.setLineNo(1);
        value.setProcessId(0L);
        value.setRouteCode(PLACEHOLDER);
        value.setRouteName(PLACEHOLDER);
        value.setColors(List.of(value.getSpecification()));
        value.setColorItems(List.of());
        value.setInventoryId(null);
        value.setItemCode(PLACEHOLDER);
        value.setItemName(PLACEHOLDER);
        value.setUnit("pcs");
        value.setQuantity(BigDecimal.ONE);
        value.setSupplierName(PLACEHOLDER);
        value.setUnitCost(null);
        value.setLineCost(null);
        value.setLossRate(BigDecimal.ZERO);
        value.setCurrencyCode(null);
        value.setMaterialSource("manual");
        value.setUnmatchedFlag(1);
        value.setLookupMessage("ERP BOM 总览缺少物料明细，按占位行归档，不参与复杂成本计算");
        value.setSubstituteFlag(0);
        value.setRemark(erpOverviewRemark(value));
        rows.add(value);
    }

    private List<Product> findProductsForErpParentCode(String parentCode) {
        List<Product> exact = safeProducts(productRepository.selectList(new LambdaQueryWrapper<Product>()
            .eq(Product::getProductCode, parentCode).eq(Product::getDeletedFlag, 0)));
        if (!exact.isEmpty()) return exact;
        String baseCode = baseProductCode(parentCode);
        if (baseCode.equals(parentCode)) return List.of();
        return safeProducts(productRepository.selectList(new LambdaQueryWrapper<Product>()
            .eq(Product::getProductCode, baseCode).eq(Product::getDeletedFlag, 0)));
    }

    private String baseProductCode(String parentCode) {
        if (parentCode == null) return "";
        String normalized = parentCode.trim();
        if (normalized.length() >= 7 && normalized.substring(0, 7).matches("[A-Z]{3}\\d{4}")) {
            return normalized.substring(0, 7);
        }
        return normalized;
    }

    private void createErpArchiveBom(List<BomImportRowVO> rows) {
        BomImportRowVO first = rows.get(0);
        ProductBom bom = new ProductBom();
        bom.setProductId(first.getProductId());
        bom.setBomCode(first.getBomCode());
        bom.setBomName("ERP 历史 BOM " + first.getSourceParentCode());
        bom.setBomType("mbom");
        bom.setBomScope("formal");
        bom.setSourceType(blankToDefault(first.getSourceOrigin(), "erp"));
        bom.setVersionNo(first.getVersionNo());
        bom.setStatus("released");
        bom.setFrozenFlag(1);
        bom.setCurrencyCode("CNY");
        bom.setRemark(erpOverviewRemark(first));
        LocalDateTime now = LocalDateTime.now();
        bom.setFrozenAt(now);
        bom.setFrozenBy(access.actor().username());
        bom.setReleasedAt(now);
        bom.setReleasedBy(access.actor().username());
        fillCreate(bom);
        bom.setUpdatedAt(now);
        bom.setUpdatedBy(access.actor().username());
        bomRepository.insert(bom);

        ProductBomRoute route = new ProductBomRoute();
        route.setProductBomId(bom.getProductBomId());
        route.setProductId(first.getProductId());
        route.setProcessId(0L);
        route.setRouteCode(PLACEHOLDER);
        route.setRouteName(PLACEHOLDER);
        route.setSharedBomGroupCode("ERP-" + first.getBomCode());
        route.setRouteVariantNo("ERP-ARCHIVE");
        route.setVariantName("ERP 历史归档占位");
        route.setVariantSourceType(ERP_PLACEHOLDER_SOURCE);
        route.setStatus("active");
        fillCreate(route);
        routeRepository.insert(route);

        ProductBomRouteColor color = new ProductBomRouteColor();
        color.setProductBomId(bom.getProductBomId());
        color.setProductBomRouteId(route.getProductBomRouteId());
        color.setColorCode(PLACEHOLDER);
        color.setColorName(blankToDefault(first.getSpecification(), PLACEHOLDER));
        color.setStatus("active");
        fillCreate(color);
        routeColorRepository.insert(color);

        ProductBomItem item = new ProductBomItem();
        item.setProductBomId(bom.getProductBomId());
        item.setProductBomRouteId(route.getProductBomRouteId());
        item.setProductId(first.getProductId());
        item.setSharedBomGroupCode(route.getSharedBomGroupCode());
        item.setInventoryId(null);
        item.setItemCode(PLACEHOLDER);
        item.setItemName(PLACEHOLDER);
        item.setSpecification(blankToDefault(first.getSpecification(), PLACEHOLDER));
        item.setLineNo(1);
        item.setQuantity(BigDecimal.ONE);
        item.setUnit("pcs");
        item.setLossRate(BigDecimal.ZERO);
        item.setSupplierNameSnapshot(PLACEHOLDER);
        BomAmountPolicy.apply(toItem(first), item, null, access.hasPermission("finance:write"), first.getCurrencyCode());
        item.setMaterialSource("manual");
        item.setUnmatchedFlag(1);
        item.setSubstituteFlag(0);
        item.setRemark(erpOverviewRemark(first));
        item.setVersionNo(first.getVersionNo());
        item.setStatus("draft");
        fillCreate(item);
        itemRepository.insert(item);
    }

    private void createReleasedBom(List<BomImportRowVO> rows) {
        BomImportRowVO first = rows.get(0);
        ProductBom bom = new ProductBom();
        bom.setProductId(first.getProductId());
        bom.setBomCode("HIS-" + first.getProductCode() + "-" + first.getVersionNo());
        bom.setBomName("历史 BOM " + first.getVersionNo());
        bom.setBomType("mbom");
        bom.setBomScope("formal");
        bom.setSourceType("import");
        bom.setVersionNo(first.getVersionNo());
        bom.setStatus("draft");
        bom.setFrozenFlag(0);
        bom.setCurrencyCode(first.getCurrencyCode() == null ? "CNY" : first.getCurrencyCode());
        fillCreate(bom);
        bomRepository.insert(bom);
        Map<String, List<BomImportRowVO>> byRoute = new LinkedHashMap<>();
        rows.forEach(row -> byRoute.computeIfAbsent(row.getRouteCode(), key -> new ArrayList<>()).add(row));
        workflowService.saveRoutes(bom.getProductBomId(), byRoute.values().stream().map(this::toRoute).toList());
        bom.setStatus("released");
        bom.setFrozenFlag(1);
        bom.setFrozenAt(LocalDateTime.now());
        bom.setFrozenBy(access.actor().username());
        bom.setReleasedAt(bom.getFrozenAt());
        bom.setReleasedBy(access.actor().username());
        bom.setUpdatedAt(bom.getFrozenAt());
        bom.setUpdatedBy(access.actor().username());
        bomRepository.updateById(bom);
    }

    private BomRouteSaveDTO toRoute(List<BomImportRowVO> rows) {
        BomImportRowVO first = rows.get(0);
        BomRouteSaveDTO route = new BomRouteSaveDTO();
        route.setProcessId(first.getProcessId());
        route.setRouteCode(first.getRouteCode());
        route.setRouteName(first.getRouteName());
        route.setColors(rows.stream().flatMap(row -> row.getColors().stream()).distinct().toList());
        route.setColorItems(rows.stream().flatMap(row -> row.getColorItems().stream())
            .collect(java.util.stream.Collectors.toMap(BomRouteColorDTO::getCodeItemId, value -> value,
                (existing, ignored) -> existing, java.util.LinkedHashMap::new)).values().stream().toList());
        route.setItems(rows.stream().map(this::toItem).toList());
        return route;
    }

    private ProductBomItemDTO toItem(BomImportRowVO row) {
        ProductBomItemDTO item = new ProductBomItemDTO();
        item.setInventoryId(row.getInventoryId()); item.setItemCode(row.getItemCode()); item.setItemName(row.getItemName());
        item.setSpecification(row.getSpecification()); item.setLineNo(row.getLineNo()); item.setQuantity(row.getQuantity());
        item.setUnit(row.getUnit()); item.setLossRate(row.getLossRate()); item.setUnitCost(row.getUnitCost());
        item.setLineCost(row.getLineCost()); item.setSupplierCode(row.getSupplierCode()); item.setSupplierName(row.getSupplierName());
        item.setCurrencyCode(row.getCurrencyCode()); item.setMaterialSource(row.getMaterialSource()); item.setUnmatchedFlag(row.getUnmatchedFlag());
        item.setLookupMessage(row.getLookupMessage());
        item.setSubstituteFlag(row.getSubstituteFlag()); item.setRemark(row.getRemark());
        return item;
    }

    private BomRouteColorDTO requireEnabledColor(String colorCode) {
        CodeItem item = codeItemRepository.selectOne(new LambdaQueryWrapper<CodeItem>()
            .eq(CodeItem::getCodeType, "color").eq(CodeItem::getCodeValue, colorCode)
            .eq(CodeItem::getStatus, "enabled").eq(CodeItem::getDeletedFlag, 0));
        if (item == null) throw new IllegalArgumentException("颜色编码不存在或已停用：" + colorCode);
        BomRouteColorDTO value = new BomRouteColorDTO();
        value.setCodeItemId(item.getCodeItemId()); value.setCodeValue(item.getCodeValue()); value.setCodeName(item.getCodeName());
        return value;
    }

    private boolean validHeader(Row header) {
        if (header == null) return false;
        DataFormatter formatter = new DataFormatter();
        for (int index = 0; index < HEADERS.size(); index++) {
            if (!HEADERS.get(index).equals(formatter.formatCellValue(header.getCell(index)).trim())) return false;
        }
        return true;
    }

    private int erpOverviewHeaderRow(org.apache.poi.ss.usermodel.Sheet sheet, DataFormatter formatter) {
        int lastCandidate = Math.min(sheet.getLastRowNum(), 20);
        for (int rowIndex = 0; rowIndex <= lastCandidate; rowIndex++) {
            Row row = sheet.getRow(rowIndex);
            if (row == null) continue;
            boolean matched = true;
            for (int cellIndex = 0; cellIndex < ERP_OVERVIEW_HEADERS.size(); cellIndex++) {
                if (!ERP_OVERVIEW_HEADERS.get(cellIndex).equals(text(row, cellIndex, formatter))) {
                    matched = false;
                    break;
                }
            }
            if (matched) return rowIndex;
        }
        return -1;
    }

    private List<BomImportRowVO> readRows(String json) {
        try { return objectMapper.readValue(json, new TypeReference<List<BomImportRowVO>>() {}); }
        catch (Exception exception) { throw new BusinessException(ErrorCodeConstants.INTERNAL_ERROR, "历史导入预览数据损坏"); }
    }

    private String writeJson(Object value) {
        try { return objectMapper.writeValueAsString(value); }
        catch (Exception exception) { throw new BusinessException(ErrorCodeConstants.INTERNAL_ERROR, "历史导入预览序列化失败"); }
    }

    private String required(String value, String field) {
        if (value == null || value.isBlank()) throw new IllegalArgumentException(field + "不能为空");
        return value.trim();
    }

    private String text(Row row, int cell, DataFormatter formatter) {
        return formatter.formatCellValue(row.getCell(cell)).trim();
    }

    private BigDecimal decimalOrNull(String value) {
        return value == null || value.isBlank() ? null : new BigDecimal(value.trim());
    }

    private Integer integerOrNull(String value) {
        if (value == null || value.isBlank()) return null;
        return new BigDecimal(value.trim()).intValue();
    }

    private String blankToDefault(String value, String defaultValue) {
        return value == null || value.isBlank() ? defaultValue : value.trim();
    }

    private String erpOverviewRemark(BomImportRowVO row) {
        return "ERP BOM 总览归档；source_parent_code=" + blankToDefault(row.getSourceParentCode(), PLACEHOLDER)
            + "; source_parent_name=" + blankToDefault(row.getSourceParentName(), PLACEHOLDER)
            + "; components=" + (row.getComponentCount() == null ? PLACEHOLDER : row.getComponentCount())
            + "; associated_skus=" + (row.getAssociatedSkuCount() == null ? PLACEHOLDER : row.getAssociatedSkuCount())
            + "; specification=" + blankToDefault(row.getSpecification(), PLACEHOLDER)
            + "; source_status=" + blankToDefault(row.getSourceStatus(), PLACEHOLDER)
            + "; source_origin=" + blankToDefault(row.getSourceOrigin(), "erp")
            + "; placeholder_fields=route/material/cost";
    }

    private List<Product> safeProducts(List<Product> values) {
        return values == null ? List.of() : values;
    }

    private void fillCreate(com.yuewei.plm.repository.entity.BaseEntity value) {
        LocalDateTime now = LocalDateTime.now();
        value.setCreatedAt(now); value.setCreatedBy(access.actor().username()); value.setUpdatedAt(now); value.setUpdatedBy(access.actor().username()); value.setDeletedFlag(0);
    }

    private BusinessException validation(String message) {
        return new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, message);
    }
}
