package com.yuewei.plm.module.bom.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.module.bom.dto.BomRouteSaveDTO;
import com.yuewei.plm.module.bom.dto.BomRouteColorDTO;
import com.yuewei.plm.module.bom.dto.ProductBomItemDTO;
import com.yuewei.plm.module.bom.entity.ProductBomImportBatch;
import com.yuewei.plm.module.bom.entity.ProductBom;
import com.yuewei.plm.module.bom.entity.ProductBomRoute;
import com.yuewei.plm.module.bom.repository.ProductBomImportBatchRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteRepository;
import com.yuewei.plm.module.pilot.PilotAccessService;
import com.yuewei.plm.module.bom.service.BomImportService;
import com.yuewei.plm.module.bom.service.BomMaterialLookup;
import com.yuewei.plm.module.bom.service.BomProcessRouteLookup;
import com.yuewei.plm.module.bom.service.ProductBomWorkflowService;
import com.yuewei.plm.module.bom.vo.BomImportErrorVO;
import com.yuewei.plm.module.bom.vo.BomImportPreviewVO;
import com.yuewei.plm.module.bom.vo.BomImportRowVO;
import com.yuewei.plm.module.code.entity.CodeItem;
import com.yuewei.plm.module.code.repository.CodeItemRepository;
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
public class BomImportServiceImpl implements BomImportService {
    private static final List<String> HEADERS = List.of(
        "行号", "路线编码", "路线名称", "适用颜色", "物料编码", "物料名称",
        "规格", "单位", "用量", "供应商", "单价", "单个成本", "损耗率", "替代料标识", "备注"
    );

    private final ProductBomImportBatchRepository batchRepository;
    private final ProductBomRepository bomRepository;
    private final BomMaterialLookup materialLookup;
    private final BomProcessRouteLookup routeLookup;
    private final ProductBomWorkflowService workflowService;
    private final CodeItemRepository codeItemRepository;
    private final ProductBomRouteRepository routeRepository;
    private final PilotAccessService access;
    private final ObjectMapper objectMapper = new ObjectMapper().findAndRegisterModules();

    @Override
    public BomImportPreviewVO preview(Long productId, Long bomId, String fileName, byte[] content) {
        access.requirePermission("bom:write");
        access.requireProduct(productId);
        ProductBom bom = bomRepository.selectById(bomId);
        if (bom == null || !productId.equals(bom.getProductId()) || !List.of("candidate", "formal").contains(bom.getBomScope())) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "BOM 不属于当前产品或不是可导入 BOM");
        }
        if (List.of("released", "frozen", "archived").contains(bom.getStatus())) {
            throw new BusinessException(ErrorCodeConstants.VERSION_FROZEN, "已发布、冻结或归档 BOM 不可导入，请复制新版本");
        }
        if (fileName == null || !fileName.toLowerCase().endsWith(".xlsx")) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "仅支持 xlsx 文件");
        }
        List<BomImportRowVO> rows = new ArrayList<>();
        List<BomImportErrorVO> errors = new ArrayList<>();
        try (XSSFWorkbook workbook = new XSSFWorkbook(new ByteArrayInputStream(content))) {
            var sheet = workbook.getNumberOfSheets() == 0 ? null : workbook.getSheetAt(0);
            if (sheet == null || !validHeader(sheet.getRow(0))) {
                errors.add(new BomImportErrorVO(1, "表头", "", "表头必须与 BOM 导入模板一致"));
            } else {
                DataFormatter formatter = new DataFormatter();
                for (int rowIndex = 1; rowIndex <= sheet.getLastRowNum(); rowIndex++) {
                    Row row = sheet.getRow(rowIndex);
                    if (row == null || formatter.formatCellValue(row.getCell(0)).isBlank()) {
                        continue;
                    }
                    if (!text(row, 10, formatter).isBlank() || !text(row, 11, formatter).isBlank()) access.requireFinanceWrite();
                    parseRow(productId, rowIndex + 1, row, formatter, rows, errors);
                }
            }
        } catch (BusinessException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "XLSX 解析失败：" + exception.getMessage());
        }
        String status = errors.isEmpty() && !rows.isEmpty() ? "ready" : "invalid";
        String token = UUID.randomUUID().toString();
        ProductBomImportBatch batch = new ProductBomImportBatch();
        batch.setProductId(productId);
        batch.setProductBomId(bomId);
        batch.setImportToken(token);
        batch.setBomScope(bom.getBomScope());
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
        return BomImportPreviewVO.builder().importToken(token).status(status)
            .totalRows(batch.getTotalRows()).validRows(rows.size()).errorRows(errors.size())
            .rows(rows).errors(errors).build();
    }

    @Override
    @Transactional
    public ProductBomImportBatch commit(String importToken) {
        access.requirePermission("bom:write");
        ProductBomImportBatch batch = batchRepository.selectOne(new LambdaQueryWrapper<ProductBomImportBatch>()
            .eq(ProductBomImportBatch::getImportToken, importToken).eq(ProductBomImportBatch::getDeletedFlag, 0));
        if (batch == null) {
            throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "导入批次不存在");
        }
        if (!"ready".equals(batch.getStatus()) || batch.getExpiresAt().isBefore(LocalDateTime.now())) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "导入批次不可提交或已过期");
        }
        access.requireProduct(batch.getProductId());
        List<BomImportRowVO> rows = readRows(batch.getPreviewJson());
        requireMoneyWrite(rows, access);
        batch.setStatus("committing");
        batch.setUpdatedAt(LocalDateTime.now());
        batch.setUpdatedBy(access.actor().username());
        int claimed = batchRepository.update(batch, new LambdaQueryWrapper<ProductBomImportBatch>()
            .eq(ProductBomImportBatch::getProductBomImportBatchId, batch.getProductBomImportBatchId())
            .eq(ProductBomImportBatch::getStatus, "ready")
            .eq(ProductBomImportBatch::getDeletedFlag, 0));
        if (claimed != 1) {
            throw new BusinessException(ErrorCodeConstants.CODE_CONFLICT, "导入令牌已被提交，不能重复使用");
        }
        Map<String, List<BomImportRowVO>> byRoute = new LinkedHashMap<>();
        rows.forEach(row -> byRoute.computeIfAbsent(row.getRouteCode(), key -> new ArrayList<>()).add(row));
        List<BomRouteSaveDTO> routes = byRoute.values().stream().map(this::toRoute).toList();
        // Stable target IDs are server-verified; never infer a priced variant from a name or amount.
        var existing = routeRepository.selectList(new LambdaQueryWrapper<ProductBomRoute>()
            .eq(ProductBomRoute::getProductBomId, batch.getProductBomId())
            .eq(ProductBomRoute::getStatus, "active")
            .eq(ProductBomRoute::getDeletedFlag, 0));
        for (BomRouteSaveDTO route : routes) {
            var matches = existing == null ? List.<ProductBomRoute>of() : existing.stream().filter(r -> route.getProcessId().equals(r.getProcessId())).toList();
            if (matches.size() > 1) throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "同工艺存在多个 BOM 变体，不能推断导入目标，请在明细编辑器核对");
            if (matches.size() == 1) route.setProductBomRouteId(matches.get(0).getProductBomRouteId());
        }
        workflowService.saveRoutes(batch.getProductBomId(), routes);
        batch.setStatus("committed");
        batch.setCommittedAt(LocalDateTime.now());
        batch.setCommittedBy(access.actor().username());
        batch.setUpdatedAt(batch.getCommittedAt());
        batch.setUpdatedBy(access.actor().username());
        batchRepository.updateById(batch);
        return batch;
    }

    /** Rechecks the persisted preview, so token-only requests cannot bypass amount authorization. */
    static void requireMoneyWrite(List<BomImportRowVO> rows, PilotAccessService access) {
        if (rows.stream().anyMatch(row -> row.getUnitCost() != null || row.getLineCost() != null
            || row.getCurrencyCode() != null && !row.getCurrencyCode().isBlank())) access.requireFinanceWrite();
    }

    @Override
    public List<BomImportErrorVO> getErrors(String importToken) {
        ProductBomImportBatch batch = batchRepository.selectOne(new LambdaQueryWrapper<ProductBomImportBatch>()
            .eq(ProductBomImportBatch::getImportToken, importToken).eq(ProductBomImportBatch::getDeletedFlag, 0));
        if (batch == null) {
            throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "导入批次不存在");
        }
        try {
            return objectMapper.readValue(batch.getErrorJson(), new TypeReference<List<BomImportErrorVO>>() {});
        } catch (Exception exception) {
            throw new BusinessException(ErrorCodeConstants.INTERNAL_ERROR, "导入错误数据损坏");
        }
    }

    @Override
    public byte[] buildErrorReport(List<BomImportErrorVO> errors) {
        try (XSSFWorkbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            var sheet = workbook.createSheet("错误报告");
            var header = sheet.createRow(0);
            List.of("原始行号", "字段", "原值", "错误原因").forEach(value ->
                header.createCell(header.getLastCellNum() < 0 ? 0 : header.getLastCellNum()).setCellValue(value));
            for (int index = 0; index < errors.size(); index++) {
                BomImportErrorVO error = errors.get(index);
                var row = sheet.createRow(index + 1);
                row.createCell(0).setCellValue(error.getRowNo());
                row.createCell(1).setCellValue(error.getField());
                row.createCell(2).setCellValue(error.getOriginalValue());
                row.createCell(3).setCellValue(error.getReason());
            }
            workbook.write(output);
            return output.toByteArray();
        } catch (Exception exception) {
            throw new BusinessException(ErrorCodeConstants.INTERNAL_ERROR, "错误报告生成失败");
        }
    }

    @Override
    public byte[] buildTemplate() {
        try (XSSFWorkbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            var sheet = workbook.createSheet("BOM导入");
            var header = sheet.createRow(0);
            for (int index = 0; index < HEADERS.size(); index++) {
                header.createCell(index).setCellValue(HEADERS.get(index));
            }
            workbook.write(output);
            return output.toByteArray();
        } catch (Exception exception) {
            throw new BusinessException(ErrorCodeConstants.INTERNAL_ERROR, "导入模板生成失败");
        }
    }

    private boolean validHeader(Row header) {
        if (header == null) return false;
        DataFormatter formatter = new DataFormatter();
        for (int index = 0; index < HEADERS.size(); index++) {
            if (!HEADERS.get(index).equals(formatter.formatCellValue(header.getCell(index)).trim())) return false;
        }
        return true;
    }

    private void parseRow(
        Long productId, int sourceRowNo, Row row, DataFormatter formatter,
        List<BomImportRowVO> rows, List<BomImportErrorVO> errors
    ) {
        String materialCode = text(row, 4, formatter);
        String routeCode = text(row, 1, formatter);
        var route = routeLookup.findByCode(productId, routeCode);
        if (route.isEmpty()) {
            errors.add(new BomImportErrorVO(sourceRowNo, "路线编码", routeCode, "产品下不存在该工艺路线"));
            return;
        }
        var material = materialLookup.findByCode(materialCode);
        try {
            String itemName = text(row, 5, formatter);
            String specification = text(row, 6, formatter);
            String unit = text(row, 7, formatter);
            String supplierName = text(row, 9, formatter);
            BigDecimal unitCost = decimalOrNull(text(row, 10, formatter));
            BigDecimal lineCost = decimalOrNull(text(row, 11, formatter));
            if (material.isPresent()) {
                BomMaterialLookup.Material matched = material.get();
                if (itemName.isBlank()) itemName = matched.inventoryName();
                if (specification.isBlank()) specification = matched.specification();
                if (unit.isBlank()) unit = matched.unit();
                if (supplierName.isBlank()) supplierName = matched.supplierName();
                if (unitCost == null && access.hasPermission("finance:write")) unitCost = matched.unitCost();
            }
            BomImportRowVO value = new BomImportRowVO();
            value.setLineNo(Integer.valueOf(text(row, 0, formatter)));
            value.setProcessId(route.get().processId());
            value.setRouteCode(route.get().routeCode());
            value.setRouteName(route.get().routeName());
            List<String> colorCodes = Arrays.stream(required(text(row, 3, formatter), "适用颜色").split("[,，]"))
                .map(String::trim).filter(color -> !color.isBlank()).distinct().toList();
            List<BomRouteColorDTO> colors = colorCodes.stream().map(this::requireEnabledColor).toList();
            value.setColorItems(colors);
            value.setColors(colors.stream().map(BomRouteColorDTO::getCodeName).toList());
            value.setInventoryId(material.map(BomMaterialLookup.Material::inventoryId).orElse(null));
            value.setItemCode(materialCode);
            value.setItemName(required(itemName, "物料名称"));
            value.setSpecification(specification);
            value.setUnit(required(unit, "单位"));
            value.setQuantity(new BigDecimal(required(text(row, 8, formatter), "用量")));
            value.setSupplierName(supplierName);
            value.setUnitCost(unitCost);
            value.setLineCost(lineCost == null && unitCost != null ? value.getQuantity().multiply(unitCost) : lineCost);
            value.setLossRate(text(row, 12, formatter).isBlank() ? BigDecimal.ZERO : new BigDecimal(text(row, 12, formatter)));
            if (access.hasPermission("finance:write")) value.setCurrencyCode(material.map(BomMaterialLookup.Material::currencyCode).filter(code -> code != null && !code.isBlank()).orElse("CNY"));
            value.setMaterialSource(material.isPresent() ? "inventory" : "manual");
            value.setUnmatchedFlag(material.isPresent() ? 0 : 1);
            value.setLookupMessage(material.isPresent() ? null : "物料编码未匹配到物料库，可先人工录入候选 BOM，正式发布前请确认物料资料。");
            value.setSubstituteFlag("1".equals(text(row, 13, formatter)) ? 1 : 0);
            value.setRemark(text(row, 14, formatter));
            if (value.getQuantity().compareTo(BigDecimal.ZERO) <= 0) throw new IllegalArgumentException("用量必须大于 0");
            if (value.getUnitCost() != null && value.getUnitCost().compareTo(BigDecimal.ZERO) < 0) throw new IllegalArgumentException("单价不能为负数");
            if (value.getLineCost() != null && value.getLineCost().compareTo(BigDecimal.ZERO) < 0) throw new IllegalArgumentException("单个成本不能为负数");
            if (value.getLossRate().compareTo(BigDecimal.ZERO) < 0 || value.getLossRate().compareTo(BigDecimal.ONE) > 0) {
                throw new IllegalArgumentException("损耗率必须在 0 到 1 之间");
            }
            rows.add(value);
        } catch (Exception exception) {
            errors.add(new BomImportErrorVO(sourceRowNo, "数据", "", exception.getMessage()));
        }
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
        item.setInventoryId(row.getInventoryId());
        item.setItemCode(row.getItemCode());
        item.setItemName(row.getItemName());
        item.setSpecification(row.getSpecification());
        item.setLineNo(row.getLineNo());
        item.setQuantity(row.getQuantity());
        item.setUnit(row.getUnit());
        item.setLossRate(row.getLossRate());
        item.setUnitCost(row.getUnitCost());
        item.setLineCost(row.getLineCost());
        item.setSupplierCode(row.getSupplierCode());
        item.setSupplierName(row.getSupplierName());
        item.setCurrencyCode(row.getCurrencyCode());
        item.setMaterialSource(row.getMaterialSource());
        item.setUnmatchedFlag(row.getUnmatchedFlag());
        item.setLookupMessage(row.getLookupMessage());
        item.setSubstituteFlag(row.getSubstituteFlag());
        item.setRemark(row.getRemark());
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

    private List<BomImportRowVO> readRows(String json) {
        try {
            return objectMapper.readValue(json, new TypeReference<List<BomImportRowVO>>() {});
        } catch (Exception exception) {
            throw new BusinessException(ErrorCodeConstants.INTERNAL_ERROR, "导入预览数据损坏");
        }
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception exception) {
            throw new BusinessException(ErrorCodeConstants.INTERNAL_ERROR, "导入预览序列化失败");
        }
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

    private void fillCreate(ProductBomImportBatch batch) {
        LocalDateTime now = LocalDateTime.now();
        batch.setCreatedAt(now);
        batch.setCreatedBy(access.actor().username());
        batch.setUpdatedAt(now);
        batch.setUpdatedBy(access.actor().username());
        batch.setDeletedFlag(0);
    }
}
