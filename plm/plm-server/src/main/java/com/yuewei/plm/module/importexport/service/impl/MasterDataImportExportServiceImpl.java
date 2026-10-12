package com.yuewei.plm.module.importexport.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.common.security.CurrentUserContext;
import com.yuewei.plm.common.util.ProductBusinessCodeGenerator;
import com.yuewei.plm.module.importexport.service.MasterDataImportExportService;
import com.yuewei.plm.module.importexport.vo.ImportBatchVO;
import com.yuewei.plm.module.importexport.vo.ImportErrorVO;
import com.yuewei.plm.module.importexport.vo.ImportPreviewRowVO;
import com.yuewei.plm.module.importexport.vo.ImportPreviewVO;
import com.yuewei.plm.module.operationlog.constant.OperationActionConstants;
import com.yuewei.plm.module.operationlog.service.OperationLogCreateCommand;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.process.entity.ProcessEntity;
import com.yuewei.plm.module.process.repository.ProcessRepository;
import com.yuewei.plm.module.product.mold.service.ProductMoldCodeService;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import jakarta.servlet.http.HttpServletRequest;
import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import lombok.RequiredArgsConstructor;
import org.apache.poi.ss.usermodel.Cell;
import org.apache.poi.ss.usermodel.CellType;
import org.apache.poi.ss.usermodel.DateUtil;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.ss.usermodel.Workbook;
import org.apache.poi.ss.usermodel.WorkbookFactory;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.BadSqlGrammarException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Service;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;
import org.springframework.web.multipart.MultipartFile;

@Service
public class MasterDataImportExportServiceImpl implements MasterDataImportExportService {

    private static final Logger log = LoggerFactory.getLogger(MasterDataImportExportServiceImpl.class);
    private static final String STATUS_READY = "ready";
    private static final String STATUS_ERROR = "error";
    private static final Set<String> OBJECT_TYPES = Set.of("product", "inventory", "process", "attachment", "product_mold_code");
    private static final Map<String, List<String>> HEADERS = Map.of(
        "product", List.of("product_code", "product_name", "product_type", "parent_product_code", "series_name", "model", "color",
            "product_specific_code", "phone_model_code", "color_code", "finished_product_code", "import_short_code",
            "version_no", "status", "current_stage", "remark"),
        "inventory", List.of("inventory_code", "inventory_name", "inventory_type", "specification", "unit", "supplier_name", "unit_cost", "currency_code", "status", "remark"),
        "process", List.of("product_code", "process_code", "process_name", "process_type", "parent_process_code", "sequence_no", "version_no", "status", "quality_requirement", "remark"),
        "attachment", List.of("owner_object_type", "owner_object_code", "file_category", "file_name", "version_no", "status", "legacy_location", "remark"),
        "product_mold_code", List.of("product_code", "mold_name", "mold_code", "key_code", "status", "remark")
    );
    private static final Map<String, List<String>> TEMPLATE_HEADERS = Map.of(
        "product", List.of("product_code", "product_name", "product_type", "parent_product_code", "series_name", "model", "color", "version_no", "status", "current_stage", "remark"),
        "inventory", List.of("物料组", "物料编码", "物料名称", "规格型号", "规格", "新增日期"),
        "process", HEADERS.get("process"),
        "attachment", HEADERS.get("attachment"),
        "product_mold_code", List.of("product_code", "mold_name", "mold_code", "key_code", "status", "remark")
    );
    private static final Map<String, List<String>> REQUIRED = Map.of(
        "product", List.of("product_code", "product_name", "product_type", "version_no", "status"),
        "inventory", List.of("inventory_code", "inventory_name", "inventory_type", "unit", "status"),
        "process", List.of("product_code", "process_code", "process_name", "process_type", "version_no", "status"),
        "attachment", List.of("owner_object_type", "owner_object_code", "file_category", "file_name", "version_no", "status"),
        "product_mold_code", List.of("mold_code")
    );
    private static final Map<String, Map<String, String>> HEADER_ALIASES = Map.of(
        "product", productHeaderAliases(),
        "inventory", inventoryHeaderAliases(),
        "process", processHeaderAliases(),
        "product_mold_code", productMoldCodeHeaderAliases()
    );
    private static final Set<String> ECOUNT_INVENTORY_REQUIRED_HEADERS = Set.of("新物料编码", "物料名称");
    private static final Set<String> ECOUNT_COMPOSITE_HEADER_PARENTS = Set.of("一级", "二级");
    private static final Set<String> STANDARD_UNITS = Set.of(
        "kg", "m²", "把", "包", "份", "个", "罐", "盒", "件", "卷", "米", "啤", "片", "瓶",
        "双", "台", "套", "条", "桶", "箱", "张", "支", "对", "辆", "袋", "筒", "付", "块", "本", "L"
    );
    private static final Set<String> PRODUCT_TYPES = Set.of("product_line", "model_variant", "sku");
    private static final Set<String> PRODUCT_STATUSES = Set.of("draft", "developing", "released", "archived");
    private static final Set<String> INVENTORY_TYPES = Set.of("material", "semi_finished", "finished", "packaging", "tooling", "fixture");
    private static final Set<String> INVENTORY_STATUSES = Set.of("draft", "available", "reserved", "consumed", "closed");
    private static final Set<String> PROCESS_TYPES = Set.of("routing", "operation", "operation_master", "route_template", "route_template_operation", "change", "quality_gate", "sample_process");
    private static final Set<String> PROCESS_STATUSES = Set.of("draft", "confirmed", "locked", "changed", "archived");
    private static final Set<String> PRODUCT_MOLD_CODE_STATUSES = Set.of("active", "archived");
    private static final String IMPORTED_PROCESS_STATUS = "confirmed";
    private static final Map<String, String> PRODUCT_STATUS_ALIASES = Map.ofEntries(
        Map.entry("active", "archived"),
        Map.entry("enabled", "archived"),
        Map.entry("valid", "archived"),
        Map.entry("current", "archived"),
        Map.entry("\u5df2\u542f\u7528", "archived"),
        Map.entry("\u542f\u7528", "archived"),
        Map.entry("\u6709\u6548", "archived"),
        Map.entry("\u6b63\u5e38", "archived"),
        Map.entry("\u5f53\u524d", "archived"),
        Map.entry("\u5df2\u5f52\u6863", "archived"),
        Map.entry("\u5f52\u6863", "archived"),
        Map.entry("\u5df2\u53d1\u5e03", "released"),
        Map.entry("\u53d1\u5e03", "released"),
        Map.entry("reviewing", "released"),
        Map.entry("\u8bc4\u5ba1\u4e2d", "released")
    );
    private static final Map<String, String> INVENTORY_STATUS_ALIASES = Map.ofEntries(
        Map.entry("active", "available"),
        Map.entry("enabled", "available"),
        Map.entry("valid", "available"),
        Map.entry("current", "available"),
        Map.entry("\u5df2\u542f\u7528", "available"),
        Map.entry("\u542f\u7528", "available"),
        Map.entry("\u6709\u6548", "available"),
        Map.entry("\u6b63\u5e38", "available"),
        Map.entry("\u53ef\u7528", "available")
    );
    private static final Map<String, String> PROCESS_STATUS_ALIASES = Map.ofEntries(
        Map.entry("active", "confirmed"),
        Map.entry("enabled", "confirmed"),
        Map.entry("valid", "confirmed"),
        Map.entry("current", "confirmed"),
        Map.entry("\u5df2\u542f\u7528", "confirmed"),
        Map.entry("\u542f\u7528", "confirmed"),
        Map.entry("\u6709\u6548", "confirmed"),
        Map.entry("\u6b63\u5e38", "confirmed"),
        Map.entry("\u5df2\u786e\u8ba4", "confirmed"),
        Map.entry("\u786e\u8ba4", "confirmed"),
        Map.entry("\u5df2\u9501\u5b9a", "locked"),
        Map.entry("\u9501\u5b9a", "locked"),
        Map.entry("\u5df2\u51bb\u7ed3", "locked"),
        Map.entry("\u51bb\u7ed3", "locked"),
        Map.entry("\u5df2\u53d8\u66f4", "changed"),
        Map.entry("\u53d8\u66f4", "changed"),
        Map.entry("\u5df2\u5f52\u6863", "archived"),
        Map.entry("\u5f52\u6863", "archived")
    );
    private static final String DEFAULT_SUPPLIER_NAME = "默认供应商";
    private static final int INITIAL_PRODUCT_STEP_NO = 1;
    private static final int PRODUCT_LINE_TERMINAL_STEP_NO = 22;
    private static final int MODEL_VARIANT_TERMINAL_STEP_NO = 18;
    private static final Set<String> TERMINAL_PRODUCT_STATUSES = Set.of("released", "archived");

    private final ProductRepository productRepository;
    private final ProcessRepository processRepository;
    private final ObjectMapper objectMapper;
    private final JdbcTemplate jdbcTemplate;
    private final OperationLogService operationLogService;
    private final Map<String, PreviewSession> sessions = new ConcurrentHashMap<>();
    private final ProductBusinessCodeGenerator businessCodeGenerator = new ProductBusinessCodeGenerator();
    @Autowired(required = false)
    private ProductMoldCodeService productMoldCodeService;

    @Autowired
    public MasterDataImportExportServiceImpl(ProductRepository productRepository,
                                              ProcessRepository processRepository,
                                              ObjectMapper objectMapper,
                                              JdbcTemplate jdbcTemplate,
                                              OperationLogService operationLogService) {
        this.productRepository = productRepository;
        this.processRepository = processRepository;
        this.objectMapper = objectMapper;
        this.jdbcTemplate = jdbcTemplate;
        this.operationLogService = operationLogService;
    }

    public MasterDataImportExportServiceImpl(ProductRepository productRepository,
                                              ProcessRepository processRepository,
                                              JdbcTemplate jdbcTemplate,
                                              OperationLogService operationLogService) {
        this(productRepository, processRepository, new ObjectMapper(), jdbcTemplate, operationLogService);
    }

    @Override
    public byte[] template(String objectType) {
        String type = normalizeType(objectType);
        List<String> sample = switch (type) {
            case "product" -> List.of("NBA4030", "亮甲 2.0", "model_variant", "", "亮甲 2.0", "iPhone18", "紫色", "V1", "archived", "seed导入", "历史项目归档");
            case "inventory" -> List.of("原料", "YL000002", "原料PC", "黑色/NEGRO/25Kg-袋", "kg", "2020/2/13");
            case "process" -> List.of("PRD-CD30-IP18-A", "PROC-CD30-SPRAY-010", "喷油", "operation", "", "10", "A", "archived", "外观无色差", "历史工艺记录");
            case "product_mold_code" -> List.of("", "亮甲2.0", "MBA10", "MBA/亮甲TPU", "active", "只关联已有 Product，不创建产品");
            default -> List.of("Product", "PRD-CD30-IP18-A", "drawing", "历史图纸V1.pdf", "V1", "archived", "共享盘/PLM历史资料", "实体文件请在对象详情页上传");
        };
        try (Workbook workbook = new XSSFWorkbook(); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            Sheet sheet = workbook.createSheet(type + "_template");
            writeRow(sheet.createRow(0), TEMPLATE_HEADERS.get(type));
            writeRow(sheet.createRow(1), sample);
            workbook.write(out);
            return out.toByteArray();
        } catch (Exception ex) {
            throw new BusinessException(ErrorCodeConstants.INTERNAL_ERROR, "模板生成失败");
        }
    }

    @Override
    public ImportPreviewVO preview(String objectType, MultipartFile file) {
        String type = normalizeType(objectType);
        if (file == null || file.isEmpty()) throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "导入文件不能为空");
        PreviewSession session = validateRows(type, file.getOriginalFilename(), readRows(file, type));
        sessions.put(session.token, session);
        return toPreviewVO(session);
    }

    @Override
    @Transactional
    public ImportPreviewVO commit(String importToken, HttpServletRequest request) {
        PreviewSession session = Optional.ofNullable(sessions.get(importToken))
            .orElseThrow(() -> new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "导入令牌不存在或已过期"));
        String operator = currentUserName();
        Long batchId = createBatch(session, operator);
        Map<String, Long> importedProductIds = new HashMap<>();
        Map<String, ProcessEntity> importRoutes = new HashMap<>();
        int success = 0;
        int fail = 0;
        for (ImportPreviewRowVO row : session.rows) {
            if (!STATUS_READY.equals(row.getStatus())) {
                insertDetail(batchId, row, "fail", row.getMessage(), operator);
                fail++;
                continue;
            }
            try {
                if ("product".equals(session.objectType)) insertProduct(row.getValues(), operator, importedProductIds);
                if ("inventory".equals(session.objectType)) insertInventory(row.getValues(), operator);
                if ("process".equals(session.objectType)) insertProcess(row.getValues(), operator, batchId, importRoutes);
                if ("product_mold_code".equals(session.objectType)) {
                    insertProductMoldCode(row.getValues(), operator, session.fileName, row.getRowNo());
                }
                if ("attachment".equals(session.objectType)) {
                    insertDetail(batchId, row, "skipped", "附件实体文件请在对象详情页上传，本次只完成清单预览", operator);
                    fail++;
                    continue;
                }
                insertDetail(batchId, row, "success", "导入成功", operator);
                success++;
            } catch (Exception ex) {
                insertDetail(batchId, row, "fail", ex.getMessage(), operator);
                fail++;
            }
        }
        updateBatch(batchId, success, fail, fail == 0 ? "completed" : "partial", operator);
        writeLog(OperationActionConstants.DATA_IMPORT_COMMIT, session.objectType, String.valueOf(batchId), session.fileName, request);
        sessions.remove(importToken);
        return toPreviewVO(session.withCommittedCounts(success, fail));
    }

    @Override
    public List<ImportErrorVO> errors(String importToken) {
        PreviewSession session = sessions.get(importToken);
        return session == null ? List.of() : session.errors;
    }

    @Override
    public byte[] export(String objectType, String keyword, String status, boolean full, HttpServletRequest request) {
        String type = normalizeType(objectType);
        List<Map<String, String>> rows = switch (type) {
            case "product" -> exportProducts(full ? null : keyword, full ? null : status);
            case "inventory" -> exportInventories(full ? null : keyword, full ? null : status);
            case "process" -> exportProcesses(full ? null : keyword, full ? null : status);
            case "product_mold_code" -> exportProductMoldCodes(full ? null : keyword, full ? null : status);
            default -> exportAttachments(full ? null : keyword, full ? null : status);
        };
        writeLog(OperationActionConstants.DATA_EXPORT, type, type, full ? "全量导出" : "筛选导出", request);
        return writeWorkbook(type + "_export", HEADERS.get(type), rows);
    }

    @Override
    public List<ImportBatchVO> batches(String objectType) {
        String sql = "select import_batch_id, object_type, file_name, total_count, success_count, fail_count, status, remark, created_at, created_by from plm_import_batch where deleted_flag = 0";
        List<Object> args = new ArrayList<>();
        if (StringUtils.hasText(objectType)) {
            sql += " and object_type = ?";
            args.add(normalizeType(objectType));
        }
        sql += " order by created_at desc limit 50";
        try {
            return jdbcTemplate.query(sql, (rs, rowNum) -> ImportBatchVO.builder()
                .importBatchId(rs.getLong("import_batch_id"))
                .objectType(rs.getString("object_type"))
                .fileName(rs.getString("file_name"))
                .totalCount(rs.getInt("total_count"))
                .successCount(rs.getInt("success_count"))
                .failCount(rs.getInt("fail_count"))
                .status(rs.getString("status"))
                .remark(rs.getString("remark"))
                .createdAt(rs.getTimestamp("created_at").toLocalDateTime())
                .createdBy(rs.getString("created_by"))
                .build(), args.toArray());
        } catch (BadSqlGrammarException ex) {
            if (isMissingImportMetadataTable(ex, "plm_import_batch")) return List.of();
            throw ex;
        }
    }

    @Override
    public ImportBatchVO batch(Long importBatchId) {
        try {
            return jdbcTemplate.queryForObject(
                "select import_batch_id, object_type, file_name, total_count, success_count, fail_count, status, remark, created_at, created_by from plm_import_batch where import_batch_id = ? and deleted_flag = 0",
                (rs, rowNum) -> ImportBatchVO.builder()
                    .importBatchId(rs.getLong("import_batch_id"))
                    .objectType(rs.getString("object_type"))
                    .fileName(rs.getString("file_name"))
                    .totalCount(rs.getInt("total_count"))
                    .successCount(rs.getInt("success_count"))
                    .failCount(rs.getInt("fail_count"))
                    .status(rs.getString("status"))
                    .remark(rs.getString("remark"))
                    .createdAt(rs.getTimestamp("created_at").toLocalDateTime())
                    .createdBy(rs.getString("created_by"))
                    .build(),
                importBatchId
            );
        } catch (BadSqlGrammarException ex) {
            if (isMissingImportMetadataTable(ex, "plm_import_batch")) {
                throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "导入批次不存在");
            }
            throw ex;
        }
    }

    private PreviewSession validateRows(String objectType, String fileName, List<RowData> dataRows) {
        String token = UUID.randomUUID().toString();
        List<ImportPreviewRowVO> rows = new ArrayList<>();
        List<ImportErrorVO> errors = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        Set<String> fileProductCodes = fileProductCodes(objectType, dataRows);
        for (RowData data : dataRows) {
            List<ImportErrorVO> rowErrors = validateRow(objectType, data, seen, fileProductCodes);
            errors.addAll(rowErrors);
            rows.add(ImportPreviewRowVO.builder()
                .rowNo(data.rowNo)
                .businessKey(businessKey(objectType, data.values))
                .status(rowErrors.isEmpty() ? STATUS_READY : STATUS_ERROR)
                .message(rowErrors.isEmpty() ? "校验通过" : rowErrors.get(0).getErrorMessage())
                .values(data.values)
                .build());
        }
        return new PreviewSession(token, objectType, fileName, rows, errors, null, null);
    }

    private Set<String> fileProductCodes(String objectType, List<RowData> dataRows) {
        if (!"product".equals(objectType)) return Set.of();
        Set<String> codes = new HashSet<>();
        for (RowData dataRow : dataRows) {
            String code = dataRow.values.get("product_code");
            if (StringUtils.hasText(code)) codes.add(code.trim());
        }
        return codes;
    }

    private List<ImportErrorVO> validateRow(String objectType, RowData row, Set<String> seen, Set<String> fileProductCodes) {
        List<ImportErrorVO> errors = new ArrayList<>();
        for (String required : REQUIRED.get(objectType)) {
            if (!StringUtils.hasText(row.values.get(required))) errors.add(error(row, required, row.values.get(required), "必填字段不能为空"));
        }
        String key = businessKey(objectType, row.values);
        if (StringUtils.hasText(key) && !seen.add(key)) errors.add(error(row, keyField(objectType), key, "文件内编码重复"));
        if ("product".equals(objectType)) validateProductRow(row, errors, fileProductCodes);
        if ("inventory".equals(objectType)) validateInventoryRow(row, errors);
        if ("process".equals(objectType)) validateProcessRow(row, errors);
        if ("attachment".equals(objectType)) validateAttachmentRow(row, errors);
        if ("product_mold_code".equals(objectType)) validateProductMoldCodeRow(row, errors);
        return errors;
    }

    private void validateProductRow(RowData row, List<ImportErrorVO> errors, Set<String> fileProductCodes) {
        String type = row.values.get("product_type");
        String status = row.values.get("status");
        String code = row.values.get("product_code");
        if (StringUtils.hasText(type) && !PRODUCT_TYPES.contains(type)) errors.add(error(row, "product_type", type, "产品类型不支持"));
        if (StringUtils.hasText(status) && !PRODUCT_STATUSES.contains(status)) errors.add(error(row, "status", status, "产品状态不支持"));
        if (existsProductCode(code)) errors.add(error(row, "product_code", code, "产品编码已存在"));
        if ("error".equals(row.values.get("match_status"))) errors.add(error(row, "normalized_code", row.values.get("normalized_code"), row.values.get("match_message")));
        if (StringUtils.hasText(row.values.get("finished_product_code")) && findProductByFinishedProductCode(row.values.get("finished_product_code")) != null) {
            errors.add(error(row, "finished_product_code", row.values.get("finished_product_code"), "成品编码已存在"));
        }
        String parentProductCode = row.values.get("parent_product_code");
        if (isChildProductType(type) && !StringUtils.hasText(parentProductCode)) {
            errors.add(error(row, "parent_product_code", "", "model_variant/SKU 必须填写上级 Product 编码"));
        }
        if (StringUtils.hasText(parentProductCode)
            && findProductByCode(parentProductCode) == null
            && !fileProductCodes.contains(parentProductCode.trim())) {
            errors.add(error(row, "parent_product_code", parentProductCode, "上级 Product 不存在"));
        }
    }

    private boolean isChildProductType(String productType) {
        return "model_variant".equals(productType) || "sku".equals(productType);
    }

    private void validateInventoryRow(RowData row, List<ImportErrorVO> errors) {
        String type = row.values.get("inventory_type");
        String status = row.values.get("status");
        String code = row.values.get("inventory_code");
        if ("unsupported".equals(type)) errors.add(error(row, "inventory_type", type, "物料组不建议自动导入 Inventory，请人工确认"));
        else if (StringUtils.hasText(type) && !INVENTORY_TYPES.contains(type)) errors.add(error(row, "inventory_type", type, "库存类型不支持"));
        if (StringUtils.hasText(status) && !INVENTORY_STATUSES.contains(status)) errors.add(error(row, "status", status, "库存状态不支持"));
        if (existsInventoryCode(code)) errors.add(error(row, "inventory_code", code, "物料/模具编码已存在"));
        parseDecimal(row.values.get("unit_cost"), row, "unit_cost", errors);
    }

    private void validateProcessRow(RowData row, List<ImportErrorVO> errors) {
        String type = row.values.get("process_type");
        String status = row.values.get("status");
        String productCode = row.values.get("product_code");
        String processCode = row.values.get("process_code");
        if (StringUtils.hasText(type) && !PROCESS_TYPES.contains(type)) errors.add(error(row, "process_type", type, "工艺类型不支持"));
        if (StringUtils.hasText(status) && !PROCESS_STATUSES.contains(status)) errors.add(error(row, "status", status, "工艺状态不支持"));
        if (requiresProductForProcessImport(type) && resolveProductForProcessImport(row.values, false, null).product() == null) errors.add(error(row, "product_code", productCode, "归属 Product 不存在"));
        parseInteger(row.values.get("sequence_no"), row, "sequence_no", errors);
    }

    private boolean requiresProductForProcessImport(String processType) {
        return Set.of("routing", "operation", "change", "quality_gate", "sample_process").contains(processType);
    }

    private void validateAttachmentRow(RowData row, List<ImportErrorVO> errors) {
        String ownerType = row.values.get("owner_object_type");
        String ownerCode = row.values.get("owner_object_code");
        if (!"Product".equals(ownerType)) errors.add(error(row, "owner_object_type", ownerType, "MVP 附件清单只校验 Product 归属"));
        else if (findProductByCode(ownerCode) == null) errors.add(error(row, "owner_object_code", ownerCode, "归属 Product 不存在"));
    }

    private void validateProductMoldCodeRow(RowData row, List<ImportErrorVO> errors) {
        String moldCode = row.values.get("mold_code");
        String status = row.values.get("status");
        if (StringUtils.hasText(status) && !PRODUCT_MOLD_CODE_STATUSES.contains(status)) {
            errors.add(error(row, "status", status, "产品模具编码状态只支持 active/archived"));
        }
        if (StringUtils.hasText(moldCode) && !moldCode.matches("[A-Z]{3}\\d{2,}")) {
            errors.add(error(row, "mold_code", moldCode, "模具编码格式不正确，应为三位字母前缀加数字"));
            return;
        }
        Product product = resolveExistingProductForMoldCode(row.values);
        if (product == null) {
            errors.add(error(row, "product_code", firstText(row.values.get("product_code"), moldCode),
                "模具编码未匹配到系统已有 Product，导入不会自动创建产品"));
            return;
        }
        row.values.put("matched_product_id", String.valueOf(product.getProductId()));
        row.values.put("matched_product_code", nullToEmpty(product.getProductCode()));
        row.values.put("matched_product_name", nullToEmpty(product.getProductName()));
        row.values.put("matched_product_status", nullToEmpty(product.getStatus()));
    }

    private void insertProduct(Map<String, String> values, String operator, Map<String, Long> importedProductIds) {
        Product product = new Product();
        String parentProductCode = trimToEmpty(values.get("parent_product_code"));
        Product parent = findProductByCode(parentProductCode);
        Long parentProductId = parent == null ? importedProductIds.get(parentProductCode) : parent.getProductId();
        product.setParentProductId(parentProductId);
        product.setProductCode(values.get("product_code"));
        product.setProductName(values.get("product_name"));
        product.setProductType(values.get("product_type"));
        product.setSeriesName(values.get("series_name"));
        product.setModel(values.get("model"));
        product.setColor(values.get("color"));
        product.setProductSpecificCode(values.get("product_specific_code"));
        product.setPhoneModelCode(values.get("phone_model_code"));
        product.setColorCode(values.get("color_code"));
        product.setFinishedProductCode(values.get("finished_product_code"));
        product.setImportShortCode(values.get("import_short_code"));
        product.setVersionNo(values.get("version_no"));
        product.setStatus(values.get("status"));
        product.setCurrentStepNo(importCurrentStepNo(product.getProductType(), product.getStatus()));
        product.setLockStatus("unlocked");
        product.setRemark(appendHistoryRemark(values.get("remark")));
        LocalDateTime now = LocalDateTime.now();
        product.setCreatedAt(now);
        product.setCreatedBy(operator);
        product.setUpdatedAt(now);
        product.setUpdatedBy(operator);
        product.setDeletedFlag(0);
        if ("released".equals(product.getStatus())) {
            product.setReleasedAt(now);
            product.setReleasedBy("history-import");
        }
        if ("archived".equals(product.getStatus())) {
            product.setArchivedAt(now);
            product.setArchivedBy("history-import");
            product.setArchiveReason("历史存档导入；archived代表流程完成并已开模完毕");
        }
        productRepository.insert(product);
        String productCode = trimToEmpty(product.getProductCode());
        if (StringUtils.hasText(productCode) && product.getProductId() != null) {
            importedProductIds.put(productCode, product.getProductId());
        }
    }

    private Integer importCurrentStepNo(String productType, String status) {
        if (!TERMINAL_PRODUCT_STATUSES.contains(status)) {
            return INITIAL_PRODUCT_STEP_NO;
        }
        return "product_line".equals(productType) ? PRODUCT_LINE_TERMINAL_STEP_NO : MODEL_VARIANT_TERMINAL_STEP_NO;
    }

    private void insertInventory(Map<String, String> values, String operator) {
        Long materialGroupId = resolveMaterialGroupId(values);
        if (materialGroupColumnExists()) {
            jdbcTemplate.update("""
                insert into plm_inventory (
                    inventory_code, inventory_name, inventory_type, specification, stock_uom,
                    supplier_name, unit_cost, currency_code, status, remark, material_group_id,
                    created_at, created_by, updated_at, updated_by, deleted_flag
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now(), ?, now(), ?, 0)
                """,
                values.get("inventory_code"), values.get("inventory_name"), values.get("inventory_type"), values.get("specification"), values.get("unit"),
                supplierNameOrDefault(values.get("supplier_name")), decimalOrNull(values.get("unit_cost")), values.get("currency_code"), values.get("status"), appendHistoryRemark(values.get("remark")), materialGroupId,
                operator, operator
            );
            return;
        }
        jdbcTemplate.update("""
            insert into plm_inventory (
                inventory_code, inventory_name, inventory_type, specification, stock_uom,
                supplier_name, unit_cost, currency_code, status, remark,
                created_at, created_by, updated_at, updated_by, deleted_flag
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now(), ?, now(), ?, 0)
            """,
            values.get("inventory_code"), values.get("inventory_name"), values.get("inventory_type"), values.get("specification"), values.get("unit"),
            supplierNameOrDefault(values.get("supplier_name")), decimalOrNull(values.get("unit_cost")), values.get("currency_code"), values.get("status"), appendHistoryRemark(values.get("remark")),
            operator, operator
        );
    }

    private void insertProductMoldCode(Map<String, String> values, String operator, String sourceFile, Integer sourceRowNo) {
        if (productMoldCodeService == null) {
            throw new BusinessException(ErrorCodeConstants.INTERNAL_ERROR, "产品-模具编码关联服务未配置");
        }
        String matchedProductId = values.get("matched_product_id");
        if (!StringUtils.hasText(matchedProductId)) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "模具编码未绑定系统已有 Product");
        }
        productMoldCodeService.upsert(
            Long.valueOf(matchedProductId),
            values.get("mold_code"),
            values.get("mold_name"),
            values.get("key_code"),
            values.get("status"),
            sourceFile,
            sourceRowNo,
            operator
        );
    }

    private Product resolveExistingProductForMoldCode(Map<String, String> values) {
        String explicitProductCode = values.get("product_code");
        if (StringUtils.hasText(explicitProductCode)) {
            Product product = findProductByCode(explicitProductCode);
            if (product == null) return null;
            values.put("match_rule", "product_code");
            return product;
        }

        String moldPrefix = values.get("mold_prefix");
        String productCodePrefix = values.get("product_code_prefix");
        String productSpecificCode = values.get("product_specific_code");
        List<Product> candidates = productRepository.selectList(new LambdaQueryWrapper<Product>()
            .eq(Product::getProductType, "product_line")
            .eq(Product::getDeletedFlag, 0)
            .and(wrapper -> wrapper
                .eq(StringUtils.hasText(moldPrefix), Product::getMoldCodePrefix, moldPrefix)
                .or()
                .eq(StringUtils.hasText(productCodePrefix), Product::getProductCodePrefix, productCodePrefix)
                .or()
                .eq(StringUtils.hasText(productSpecificCode), Product::getProductSpecificCode, productSpecificCode)));
        candidates = candidates == null ? List.of() : candidates;
        if (candidates.size() == 1) {
            values.put("match_rule", "mold_prefix_or_product_prefix");
            return candidates.get(0);
        }

        String moldName = trimToEmpty(values.get("mold_name"));
        List<Product> nameMatches = candidates.stream()
            .filter(product -> equalsIgnoreCase(moldName, product.getProductName())
                || equalsIgnoreCase(moldName, product.getSeriesName()))
            .toList();
        if (nameMatches.size() == 1) {
            values.put("match_rule", "mold_name");
            return nameMatches.get(0);
        }
        return null;
    }

    private Long resolveMaterialGroupId(Map<String, String> values) {
        Optional<String> groupKey = materialGroupKey(values);
        if (groupKey.isEmpty() || !materialGroupDictionaryExists()) {
            return null;
        }
        try {
            return jdbcTemplate.queryForObject(
                """
                select material_group_id
                  from plm_material_group
                 where source_system = 'ECOUNT'
                   and group_key = ?
                   and deleted_flag = 0
                 order by material_group_id
                 limit 1
                """,
                Long.class,
                groupKey.get()
            );
        } catch (DataAccessException exception) {
            return null;
        }
    }

    private Optional<String> materialGroupKey(Map<String, String> values) {
        String majorCode = normalizeGroupCode(values.get("ecount_major_code"));
        String majorName = trimToEmpty(values.get("ecount_major_name"));
        if (!StringUtils.hasText(majorCode) || !StringUtils.hasText(majorName)) {
            return Optional.empty();
        }

        return Optional.of("L1:" + majorCode + ":" + majorName);
    }

    private boolean materialGroupDictionaryExists() {
        return countMetadata(
            "select count(*) from information_schema.tables where table_name = 'plm_material_group'"
        );
    }

    private boolean materialGroupColumnExists() {
        return countMetadata(
            "select count(*) from information_schema.columns where table_name = 'plm_inventory' and column_name = 'material_group_id'"
        );
    }

    private boolean countMetadata(String sql) {
        try {
            Integer count = jdbcTemplate.queryForObject(sql, Integer.class);
            return count != null && count > 0;
        } catch (DataAccessException exception) {
            return false;
        }
    }

    private void insertProcess(Map<String, String> values, String operator, Long batchId, Map<String, ProcessEntity> importRoutes) {
        ProcessProductResolution resolution = resolveProductForProcessImport(values, true, operator);
        Product product = resolution.product();
        ProcessEntity parent = findProcessByCode(values.get("parent_process_code"));
        if (parent == null && !StringUtils.hasText(values.get("parent_process_code")) && "operation".equals(values.get("process_type")) && product != null) {
            parent = getOrCreateImportRoute(values, product, operator, batchId, importRoutes);
        }
        ProcessEntity existing = findProcessByCode(values.get("process_code"));
        ProcessEntity process = existing == null ? new ProcessEntity() : existing;
        process.setProductId(product == null ? parent == null ? null : parent.getProductId() : product.getProductId());
        process.setParentProcessId(parent == null ? null : parent.getProcessId());
        process.setProcessCode(values.get("process_code"));
        process.setProcessName(values.get("process_name"));
        process.setProcessType(values.get("process_type"));
        process.setProductSpecificCode(firstText(product == null ? "" : product.getProductSpecificCode(), resolution.legacyCode().productSpecificCode(), normalizeBusinessCode(values.get("product_code"))));
        process.setPhoneModelCode(product == null ? null : product.getPhoneModelCode());
        process.setColorCode(product == null ? null : product.getColorCode());
        applyLegacyProcessCode(process, resolution.legacyCode());
        if ("operation".equals(process.getProcessType())) {
            process.setOperationMasterProcessId(resolveImportedOperationMaster(process));
            process.setProcessParamJson("{\"operationSource\":\"imported_snapshot\"}");
        }
        process.setSequenceNo(integerOrNull(values.get("sequence_no")));
        process.setVersionNo(values.get("version_no"));
        process.setStatus(IMPORTED_PROCESS_STATUS);
        process.setQualityRequirement(values.get("quality_requirement"));
        process.setRemark(appendHistoryRemark(values.get("remark")));
        LocalDateTime now = LocalDateTime.now();
        process.setUpdatedAt(now);
        process.setUpdatedBy(operator);
        process.setDeletedFlag(0);
        if (existing == null) {
            process.setCreatedAt(now);
            process.setCreatedBy(operator);
            processRepository.insert(process);
        } else {
            processRepository.updateById(process);
        }
    }

    private ProcessEntity getOrCreateImportRoute(Map<String, String> values, Product product, String operator, Long batchId, Map<String, ProcessEntity> importRoutes) {
        String key = product.getProductId() == null
            ? "CODE:" + firstText(product.getProductCode(), product.getProductSpecificCode())
            : "ID:" + product.getProductId();
        ProcessEntity route = importRoutes.get(key);
        if (route != null) return route;

        LocalDateTime now = LocalDateTime.now();
        route = new ProcessEntity();
        String routeCode = "ROUTE-" + routeProductCode(product) + "-IMPORT-" + (batchId == null ? "NA" : batchId);
        ProcessEntity existingRoute = findProcessByCode(routeCode);
        if (existingRoute != null) {
            importRoutes.put(key, existingRoute);
            return existingRoute;
        }
        route.setProductId(product.getProductId());
        route.setProcessCode(routeCode);
        route.setProcessName(routeProductName(product) + " \u5de5\u827a\u8def\u7ebf");
        route.setProcessType("routing");
        route.setProductSpecificCode(product.getProductSpecificCode());
        route.setPhoneModelCode(product.getPhoneModelCode());
        route.setColorCode(product.getColorCode());
        route.setVersionNo(firstText(values.get("version_no"), "V1"));
        route.setStatus(IMPORTED_PROCESS_STATUS);
        route.setRemark(appendHistoryRemark("\u5de5\u827a\u5bfc\u5165\u81ea\u52a8\u751f\u6210\u8def\u7ebf"));
        route.setCreatedAt(now);
        route.setCreatedBy(operator);
        route.setUpdatedAt(now);
        route.setUpdatedBy(operator);
        route.setDeletedFlag(0);
        processRepository.insert(route);
        importRoutes.put(key, route);
        return route;
    }

    private String routeProductCode(Product product) {
        return firstText(normalizeBusinessCode(product.getProductCode()), normalizeBusinessCode(product.getProductSpecificCode()), "UNKNOWN");
    }

    private String routeProductName(Product product) {
        return firstText(product.getProductName(), product.getProductCode(), product.getProductSpecificCode(), "Product");
    }

    private void applyLegacyProcessCode(ProcessEntity process, LegacyProcessCode legacyCode) {
        if (legacyCode == LegacyProcessCode.empty()) return;
        process.setOperationCraftCode(legacyCode.operationCode());
        process.setMaterialStatusCode(legacyCode.operationCode());
        if (isBusinessOperationCodeAvailable(legacyCode.normalizedCode(), process.getProcessId())) {
            process.setBusinessOperationCode(legacyCode.normalizedCode());
        }
        process.setBusinessOperationCodeManualFlag(false);
        process.setFinishedProductFlag(legacyCode.finishedProduct());
        if (legacyCode.finishedProduct()) {
            process.setGeneratedFinishedProductCode(legacyCode.normalizedCode());
        }
    }

    private Long resolveImportedOperationMaster(ProcessEntity importedOperation) {
        List<ProcessEntity> masters = processRepository.selectList(new LambdaQueryWrapper<ProcessEntity>()
            .eq(ProcessEntity::getProcessType, "operation_master")
            .in(ProcessEntity::getStatus, List.of("confirmed", "locked"))
            .eq(ProcessEntity::getDeletedFlag, 0));
        if (masters == null || masters.isEmpty()) return null;

        List<ProcessEntity> codeMatches = masters.stream()
            .filter(master -> equalsIgnoreCase(master.getProcessCode(), importedOperation.getProcessCode()))
            .toList();
        if (codeMatches.size() == 1) return codeMatches.get(0).getProcessId();

        String craftCode = normalizeBusinessCode(importedOperation.getOperationCraftCode());
        if (StringUtils.hasText(craftCode)) {
            List<ProcessEntity> craftMatches = masters.stream()
                .filter(master -> equalsIgnoreCase(operationCraftCode(master), craftCode))
                .toList();
            if (craftMatches.size() == 1) return craftMatches.get(0).getProcessId();
        }

        List<ProcessEntity> nameMatches = masters.stream()
            .filter(master -> equalsIgnoreCase(master.getProcessName(), importedOperation.getProcessName()))
            .toList();
        return nameMatches.size() == 1 ? nameMatches.get(0).getProcessId() : null;
    }

    private String operationCraftCode(ProcessEntity master) {
        String direct = normalizeBusinessCode(master.getOperationCraftCode());
        if (StringUtils.hasText(direct)) return direct;
        String json = master.getProcessParamJson();
        if (!StringUtils.hasText(json)) return "";
        try {
            JsonNode value = objectMapper.readTree(json).get("operationCraftCode");
            return value == null ? "" : normalizeBusinessCode(value.asText());
        } catch (Exception ignored) {
            return "";
        }
    }

    private List<RowData> readRows(MultipartFile file, String objectType) {
        String fileName = file.getOriginalFilename() == null ? "" : file.getOriginalFilename().toLowerCase(Locale.ROOT);
        if (fileName.endsWith(".csv")) return readCsvRows(file, objectType);
        return readExcelRows(file, objectType);
    }

    private List<RowData> readExcelRows(MultipartFile file, String objectType) {
        try (InputStream input = file.getInputStream(); Workbook workbook = WorkbookFactory.create(input)) {
            Sheet sheet = selectImportSheet(workbook, objectType);
            if (sheet == null || sheet.getPhysicalNumberOfRows() < 1) throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "导入模板不能为空");
            HeaderLayout layout = resolveExcelHeaderLayout(sheet, objectType);
            Map<Integer, String> headers = layout.headers();
            log.info("Import preview Excel headers detected: objectType={}, fileName={}, sheet={}, firstDataRowIndex={}, headers={}",
                objectType, file.getOriginalFilename(), sheet.getSheetName(), layout.firstDataRowIndex(), headers.values());
            validateRequiredHeaders(objectType, headers);
            List<RowData> rows = new ArrayList<>();
            for (int i = layout.firstDataRowIndex(); i <= sheet.getLastRowNum(); i++) {
                Row row = sheet.getRow(i);
                if (row == null) continue;
                Map<String, String> values = new LinkedHashMap<>();
                boolean hasValue = false;
                for (Map.Entry<Integer, String> entry : headers.entrySet()) {
                    String value = cellString(row.getCell(entry.getKey())).trim();
                    if (StringUtils.hasText(value)) hasValue = true;
                    values.put(entry.getValue(), value);
                }
                normalizeRowValues(objectType, values);
                if (hasValue) rows.add(new RowData(i + 1, values));
            }
            return rows;
        } catch (BusinessException ex) {
            throw ex;
        } catch (Exception ex) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "仅支持 .xlsx/.xls/.csv 模板文件");
        }
    }

    private List<RowData> readCsvRows(MultipartFile file, String objectType) {
        try (InputStream input = file.getInputStream();
             BufferedReader reader = new BufferedReader(new InputStreamReader(input, StandardCharsets.UTF_8))) {
            List<List<String>> lines = new ArrayList<>();
            String line;
            while ((line = reader.readLine()) != null) {
                lines.add(parseCsvLine(line));
            }
            if (lines.isEmpty()) throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "导入模板不能为空");
            HeaderLayout layout = resolveCsvHeaderLayout(lines, objectType);
            validateRequiredHeaders(objectType, layout.headers());
            List<RowData> rows = new ArrayList<>();
            for (int i = layout.firstDataRowIndex(); i < lines.size(); i++) {
                List<String> lineValues = lines.get(i);
                Map<String, String> values = new LinkedHashMap<>();
                boolean hasValue = false;
                for (Map.Entry<Integer, String> entry : layout.headers().entrySet()) {
                    String value = entry.getKey() < lineValues.size() ? lineValues.get(entry.getKey()).trim() : "";
                    if (StringUtils.hasText(value)) hasValue = true;
                    values.put(entry.getValue(), value);
                }
                normalizeRowValues(objectType, values);
                if (hasValue) rows.add(new RowData(i + 1, values));
            }
            return rows;
        } catch (BusinessException ex) {
            throw ex;
        } catch (Exception ex) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "CSV 模板文件解析失败");
        }
    }

    private Sheet selectImportSheet(Workbook workbook, String objectType) {
        if ("inventory".equals(objectType)) {
            Sheet ecountSheet = workbook.getSheet("物料编码表");
            if (ecountSheet != null) return ecountSheet;
        }
        Sheet templateSheet = workbook.getSheet(objectType + "_template");
        if (templateSheet != null) return templateSheet;
        for (int sheetIndex = 0; sheetIndex < workbook.getNumberOfSheets(); sheetIndex++) {
            Sheet sheet = workbook.getSheetAt(sheetIndex);
            if (sheetContainsRequiredHeaders(sheet, objectType)) return sheet;
        }
        return workbook.getSheetAt(0);
    }

    private boolean sheetContainsRequiredHeaders(Sheet sheet, String objectType) {
        if (sheet == null) return false;
        int last = Math.min(sheet.getLastRowNum(), 4);
        for (int rowIndex = 0; rowIndex <= last; rowIndex++) {
            Map<Integer, String> headers = simpleExcelHeaders(sheet.getRow(rowIndex), objectType);
            if (REQUIRED.get(objectType).stream().allMatch(required -> hasRequiredHeader(objectType, headers, required))) {
                return true;
            }
        }
        return false;
    }

    private HeaderLayout resolveExcelHeaderLayout(Sheet sheet, String objectType) {
        if ("inventory".equals(objectType)) {
            int ecountHeaderRowIndex = findEcountExcelHeaderRow(sheet);
            if (ecountHeaderRowIndex >= 0) return ecountExcelHeaderLayout(sheet, objectType, ecountHeaderRowIndex);
        }
        return simpleExcelHeaderLayout(sheet, objectType);
    }

    private HeaderLayout simpleExcelHeaderLayout(Sheet sheet, String objectType) {
        int last = Math.min(sheet.getLastRowNum(), 9);
        HeaderLayout fallback = new HeaderLayout(simpleExcelHeaders(sheet.getRow(0), objectType), 1);
        for (int rowIndex = 0; rowIndex <= last; rowIndex++) {
            Map<Integer, String> headers = simpleExcelHeaders(sheet.getRow(rowIndex), objectType);
            boolean containsRequiredHeaders = REQUIRED.get(objectType).stream()
                .allMatch(required -> hasRequiredHeader(objectType, headers, required));
            if (containsRequiredHeaders) {
                return new HeaderLayout(headers, rowIndex + 1);
            }
        }
        return fallback;
    }

    private HeaderLayout resolveCsvHeaderLayout(List<List<String>> lines, String objectType) {
        if ("inventory".equals(objectType)) {
            int ecountHeaderRowIndex = findEcountCsvHeaderRow(lines);
            if (ecountHeaderRowIndex >= 0) return ecountCsvHeaderLayout(lines, objectType, ecountHeaderRowIndex);
        }
        return new HeaderLayout(simpleCsvHeaders(lines.get(0), objectType), 1);
    }

    private Map<Integer, String> simpleExcelHeaders(Row headerRow, String objectType) {
        Map<Integer, String> headers = new LinkedHashMap<>();
        Set<String> mappedHeaders = new HashSet<>();
        if (headerRow == null) return headers;
        Set<String> normalizedRawHeaders = normalizedExcelHeaderTexts(headerRow);
        for (Cell cell : headerRow) {
            String rawHeader = cellString(cell);
            String header = shouldTreatSpecificationColumnAsUnit(objectType, rawHeader, normalizedRawHeaders)
                ? "unit"
                : canonicalHeader(objectType, rawHeader);
            if (StringUtils.hasText(header) && mappedHeaders.add(header)) headers.put(cell.getColumnIndex(), header);
        }
        return headers;
    }

    private Map<Integer, String> simpleCsvHeaders(List<String> headerRow, String objectType) {
        Map<Integer, String> headers = new LinkedHashMap<>();
        Set<String> mappedHeaders = new HashSet<>();
        Set<String> normalizedRawHeaders = normalizedCsvHeaderTexts(headerRow);
        for (int i = 0; i < headerRow.size(); i++) {
            String rawHeader = headerRow.get(i);
            String header = shouldTreatSpecificationColumnAsUnit(objectType, rawHeader, normalizedRawHeaders)
                ? "unit"
                : canonicalHeader(objectType, rawHeader);
            if (StringUtils.hasText(header) && mappedHeaders.add(header)) headers.put(i, header);
        }
        return headers;
    }

    private Set<String> normalizedExcelHeaderTexts(Row headerRow) {
        Set<String> headers = new HashSet<>();
        for (Cell cell : headerRow) headers.add(normalizeHeaderText(cellString(cell)));
        return headers;
    }

    private Set<String> normalizedCsvHeaderTexts(List<String> headerRow) {
        Set<String> headers = new HashSet<>();
        for (String header : headerRow) headers.add(normalizeHeaderText(header));
        return headers;
    }

    private boolean shouldTreatSpecificationColumnAsUnit(String objectType, String rawHeader, Set<String> normalizedRawHeaders) {
        if (!"inventory".equals(objectType) || !"规格".equals(normalizeHeaderText(rawHeader))) return false;
        boolean hasSpecificationModel = normalizedRawHeaders.contains(normalizeHeaderText("规格型号"));
        boolean hasExplicitUnit = normalizedRawHeaders.contains(normalizeHeaderText("单位"))
            || normalizedRawHeaders.contains(normalizeHeaderText("基本单位"))
            || normalizedRawHeaders.contains(normalizeHeaderText("库存单位"))
            || normalizedRawHeaders.contains(normalizeHeaderText("计量单位"));
        return hasSpecificationModel && !hasExplicitUnit;
    }

    private int findEcountExcelHeaderRow(Sheet sheet) {
        int last = Math.min(sheet.getLastRowNum(), 4);
        for (int rowIndex = 0; rowIndex <= last; rowIndex++) {
            Row row = sheet.getRow(rowIndex);
            if (rowContainsAll(row, ECOUNT_INVENTORY_REQUIRED_HEADERS)) return rowIndex;
        }
        return -1;
    }

    private int findEcountCsvHeaderRow(List<List<String>> lines) {
        int last = Math.min(lines.size(), 5);
        for (int rowIndex = 0; rowIndex < last; rowIndex++) {
            Set<String> values = new HashSet<>();
            for (String value : lines.get(rowIndex)) values.add(value == null ? "" : value.trim());
            if (values.containsAll(ECOUNT_INVENTORY_REQUIRED_HEADERS)) return rowIndex;
        }
        return -1;
    }

    private boolean rowContainsAll(Row row, Set<String> requiredValues) {
        if (row == null) return false;
        Set<String> values = new HashSet<>();
        for (Cell cell : row) values.add(cellString(cell).trim());
        return values.containsAll(requiredValues);
    }

    private HeaderLayout ecountExcelHeaderLayout(Sheet sheet, String objectType, int headerRowIndex) {
        Row mainHeader = sheet.getRow(headerRowIndex);
        Row subHeader = sheet.getRow(headerRowIndex + 1);
        short mainLast = mainHeader == null ? 0 : mainHeader.getLastCellNum();
        short subLast = subHeader == null ? 0 : subHeader.getLastCellNum();
        int lastColumn = Math.max(0, Math.max(mainLast, subLast));
        Map<Integer, String> headers = new LinkedHashMap<>();
        Set<String> mappedHeaders = new HashSet<>();
        String parentHeader = "";
        for (int columnIndex = 0; columnIndex < lastColumn; columnIndex++) {
            String main = cellString(mainHeader == null ? null : mainHeader.getCell(columnIndex)).trim();
            if (StringUtils.hasText(main)) parentHeader = main;
            String sub = cellString(subHeader == null ? null : subHeader.getCell(columnIndex)).trim();
            String header = ecountRawHeader(parentHeader, main, sub);
            String canonical = canonicalHeader(objectType, header);
            if (StringUtils.hasText(canonical) && mappedHeaders.add(canonical)) headers.put(columnIndex, canonical);
        }
        int dataStart = rowLooksLikeData(sheet.getRow(headerRowIndex + 2), headers) ? headerRowIndex + 2 : headerRowIndex + 3;
        return new HeaderLayout(headers, dataStart);
    }

    private HeaderLayout ecountCsvHeaderLayout(List<List<String>> lines, String objectType, int headerRowIndex) {
        List<String> mainHeader = lines.get(headerRowIndex);
        List<String> subHeader = headerRowIndex + 1 < lines.size() ? lines.get(headerRowIndex + 1) : List.of();
        int lastColumn = Math.max(mainHeader.size(), subHeader.size());
        Map<Integer, String> headers = new LinkedHashMap<>();
        Set<String> mappedHeaders = new HashSet<>();
        String parentHeader = "";
        for (int columnIndex = 0; columnIndex < lastColumn; columnIndex++) {
            String main = columnIndex < mainHeader.size() ? mainHeader.get(columnIndex).trim() : "";
            if (StringUtils.hasText(main)) parentHeader = main;
            String sub = columnIndex < subHeader.size() ? subHeader.get(columnIndex).trim() : "";
            String canonical = canonicalHeader(objectType, ecountRawHeader(parentHeader, main, sub));
            if (StringUtils.hasText(canonical) && mappedHeaders.add(canonical)) headers.put(columnIndex, canonical);
        }
        int candidate = headerRowIndex + 2;
        int dataStart = candidate < lines.size() && lineLooksLikeData(lines.get(candidate), headers) ? candidate : headerRowIndex + 3;
        return new HeaderLayout(headers, dataStart);
    }

    private String ecountRawHeader(String parentHeader, String mainHeader, String subHeader) {
        if (StringUtils.hasText(subHeader) && ECOUNT_COMPOSITE_HEADER_PARENTS.contains(parentHeader)) {
            return parentHeader + "." + subHeader;
        }
        return StringUtils.hasText(mainHeader) ? mainHeader : subHeader;
    }

    private boolean rowLooksLikeData(Row row, Map<Integer, String> headers) {
        if (row == null) return false;
        for (Map.Entry<Integer, String> entry : headers.entrySet()) {
            if (List.of("inventory_code", "inventory_name").contains(entry.getValue())
                && StringUtils.hasText(cellString(row.getCell(entry.getKey())))) return true;
        }
        return false;
    }

    private boolean lineLooksLikeData(List<String> line, Map<Integer, String> headers) {
        for (Map.Entry<Integer, String> entry : headers.entrySet()) {
            if (List.of("inventory_code", "inventory_name").contains(entry.getValue())
                && entry.getKey() < line.size()
                && StringUtils.hasText(line.get(entry.getKey()))) return true;
        }
        return false;
    }

    private void validateRequiredHeaders(String objectType, Map<Integer, String> headers) {
        for (String required : REQUIRED.get(objectType)) {
            if (!hasRequiredHeader(objectType, headers, required)) {
                throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "模板缺少必填列：" + required);
            }
        }
    }

    private boolean hasRequiredHeader(String objectType, Map<Integer, String> headers, String required) {
        if (headers.containsValue(required)) return true;
        if (!"inventory".equals(objectType)) return false;
        if ("status".equals(required)) return true;
        if ("inventory_type".equals(required)) {
            return headers.containsValue("ecount_major_code") || headers.containsValue("ecount_major_name");
        }
        return false;
    }

    private void normalizeRowValues(String objectType, Map<String, String> values) {
        if ("product".equals(objectType)) {
            normalizeProductRowValues(values);
            return;
        }
        if ("process".equals(objectType)) {
            values.put("product_code", normalizeBusinessCode(values.get("product_code")));
            LegacyProcessCode legacyCode = parseLegacyProcessCode(values.get("product_code"));
            values.put("legacy_product_specific_code", legacyCode.productSpecificCode());
            values.put("legacy_operation_code", legacyCode.operationCode());
            values.put("status", IMPORTED_PROCESS_STATUS);
            return;
        }
        if ("product_mold_code".equals(objectType)) {
            normalizeProductMoldCodeRowValues(values);
            return;
        }
        if (!"inventory".equals(objectType)) return;
        normalizeInventoryEcountGroup(values);
        normalizeInventoryMajorAlias(values);
        values.put("inventory_code", normalizeInventoryCode(values));
        values.put("unit", normalizeInventoryUnit(values.get("unit")));
        values.put("barcode", normalizeBlankToken(values.get("barcode")));
        if (!StringUtils.hasText(values.get("inventory_type"))) values.put("inventory_type", deriveInventoryType(values));
        values.put("status", normalizeStatus(values.get("status"), INVENTORY_STATUS_ALIASES));
        if (!StringUtils.hasText(values.get("status"))) values.put("status", "available");
        if (!StringUtils.hasText(values.get("currency_code"))) values.put("currency_code", "CNY");
        if (!StringUtils.hasText(values.get("supplier_name"))) values.put("supplier_name", DEFAULT_SUPPLIER_NAME);
        values.put("remark", appendEcountRemark(values));
    }

    private void normalizeProductRowValues(Map<String, String> values) {
        values.put("status", normalizeStatus(values.get("status"), PRODUCT_STATUS_ALIASES));
        for (String key : List.of("product_specific_code", "phone_model_code", "color_code", "finished_product_code", "import_short_code")) {
            values.put(key, normalizeBusinessCode(values.get(key)));
        }
        CodeDetection detection = detectImportCode(firstText(
            values.get("finished_product_code"),
            values.get("import_short_code")
        ));
        values.put("normalized_code", detection.normalizedCode());
        values.put("detected_object_type", detection.objectType());
        values.put("matched_product_code", detection.matchedProductCode());
        values.put("matched_finished_code", detection.matchedFinishedCode());
        values.put("match_status", detection.matchStatus());
        values.put("match_message", detection.matchMessage());
    }

    private void normalizeProductMoldCodeRowValues(Map<String, String> values) {
        values.put("product_code", normalizeBusinessCode(values.get("product_code")));
        values.put("mold_code", normalizeBusinessCode(firstText(values.get("mold_code"), values.get("mould_code"))));
        values.put("mold_name", trimToEmpty(firstText(values.get("mold_name"), values.get("mould_name"))));
        values.put("key_code", trimToEmpty(values.get("key_code")));
        values.put("status", StringUtils.hasText(values.get("status")) ? values.get("status").trim().toLowerCase(Locale.ROOT) : "active");
        String moldCode = values.get("mold_code");
        if (StringUtils.hasText(moldCode) && moldCode.length() >= 3) {
            values.put("mold_prefix", moldCode.substring(0, 3));
            values.put("product_code_prefix", "N" + moldCode.substring(1, 3));
            try {
                ProductBusinessCodeGenerator.MoldCodeParts parts =
                    businessCodeGenerator.parseMoldCode(moldCode, null, List.of(), null);
                values.put("product_specific_code", parts.productSpecificCode());
                values.put("material_code", nullToEmpty(parts.materialCode()));
            } catch (BusinessException ex) {
                values.put("product_specific_code", "");
                values.put("material_code", "");
            }
        } else {
            values.put("mold_prefix", "");
            values.put("product_code_prefix", "");
            values.put("product_specific_code", "");
            values.put("material_code", "");
        }
    }

    private String normalizeStatus(String status, Map<String, String> aliases) {
        if (!StringUtils.hasText(status)) return "";
        String normalized = status.trim().replace("\u3000", "");
        String key = normalized.toLowerCase(Locale.ROOT);
        return aliases.getOrDefault(key, normalized);
    }

    private void normalizeInventoryEcountGroup(Map<String, String> values) {
        if (StringUtils.hasText(values.get("ecount_major_code"))) return;
        String majorName = trimToEmpty(values.get("ecount_major_name"));
        int split = majorName.indexOf(' ');
        if (split <= 0) return;
        String code = normalizeGroupCode(majorName.substring(0, split));
        if (!StringUtils.hasText(code)) return;
        values.put("ecount_major_code", code);
        values.put("ecount_major_name", majorName.substring(split + 1).trim());
    }

    private void normalizeInventoryMajorAlias(Map<String, String> values) {
        String majorCode = normalizeGroupCode(values.get("ecount_major_code"));
        String majorName = trimToEmpty(values.get("ecount_major_name"));
        if ("0".equals(majorCode) && "\u8f85\u6599".equals(majorName)) {
            values.put("ecount_major_code", "FL");
            values.put("ecount_major_name", "\u8f85\u6599");
        } else if (StringUtils.hasText(majorCode)) {
            values.put("ecount_major_code", majorCode);
        }
    }

    private String normalizeInventoryCode(Map<String, String> values) {
        String code = trimToEmpty(values.get("inventory_code")).replace("\u3000", "");
        if (!code.matches("\\d{3,}")) return code;
        String majorCode = normalizeGroupCode(values.get("ecount_major_code"));
        if (!StringUtils.hasText(majorCode)) return code;
        String minorCode = normalizeGroupCode(values.get("ecount_minor_code"));
        String sequenceCode = minorCode.matches("\\d{3,}") ? minorCode : code;
        return majorCode + sequenceCode;
    }

    private String normalizeInventoryUnit(String unit) {
        if (!StringUtils.hasText(unit)) return "";
        String raw = unit.trim();
        String compact = raw
            .replace("\u3000", "")
            .replace(" ", "")
            .replace("：", ":")
            .trim();
        if ("kg".equalsIgnoreCase(compact)) return "kg";
        if ("l".equalsIgnoreCase(compact)) return "L";
        if ("m2".equalsIgnoreCase(compact) || "m²".equalsIgnoreCase(compact)) return "m²";
        for (String standardUnit : STANDARD_UNITS) {
            if (compact.startsWith(standardUnit)) return standardUnit;
        }
        return raw;
    }

    private String normalizeBlankToken(String value) {
        if (!StringUtils.hasText(value)) return "";
        String normalized = value.trim();
        return Set.of("#N/A", "N/A", "NA").contains(normalized.toUpperCase(Locale.ROOT)) ? "" : normalized;
    }

    private String deriveInventoryType(Map<String, String> values) {
        String majorCode = values.getOrDefault("ecount_major_code", "").trim().toUpperCase(Locale.ROOT);
        String majorName = values.getOrDefault("ecount_major_name", "").trim();
        if ("YL".equals(majorCode)
            || ("GL".equals(majorCode) && !majorName.contains("辅料"))
            || majorName.contains("原料")
            || majorName.contains("钢料")
            || majorName.contains("铜料")) return "material";
        if (Set.of("FL", "KGFL", "NHA", "NAR", "0").contains(majorCode) || majorName.contains("辅料")) return "packaging";
        if (Set.of("GJ", "HE", "WJ", "MJ", "KGMJ", "SB", "KGSB").contains(majorCode)
            || majorName.contains("工具")
            || majorName.contains("模具")
            || majorName.contains("模架")
            || majorName.contains("模芯")
            || majorName.contains("设备")) return "tooling";
        if (Set.of("JG", "RC", "WX").contains(majorCode)
            || majorName.contains("加工")
            || majorName.contains("费用")
            || majorName.contains("日常工作")) return "unsupported";
        return "";
    }

    private String appendEcountRemark(Map<String, String> values) {
        List<String> parts = new ArrayList<>();
        addEcountRemarkPart(parts, "一级", values.get("ecount_major_code"), values.get("ecount_major_name"));
        addEcountRemarkPart(parts, "二级", values.get("ecount_minor_code"), values.get("ecount_minor_name"));
        addEcountRemarkPart(parts, "旧编码", values.get("legacy_inventory_code"));
        addEcountRemarkPart(parts, "条码", values.get("barcode"));
        addEcountRemarkPart(parts, "新增日期", values.get("source_created_date"));
        if (parts.isEmpty()) return values.getOrDefault("remark", "");
        String sourceRemark = "ECOUNT导入：" + String.join("，", parts);
        String remark = values.get("remark");
        return StringUtils.hasText(remark) ? remark.trim() + "；" + sourceRemark : sourceRemark;
    }

    private void addEcountRemarkPart(List<String> parts, String label, String code, String name) {
        if (StringUtils.hasText(code) && StringUtils.hasText(name)) parts.add(label + "=" + code.trim() + "/" + name.trim());
        else if (StringUtils.hasText(code)) parts.add(label + "=" + code.trim());
        else if (StringUtils.hasText(name)) parts.add(label + "=" + name.trim());
    }

    private void addEcountRemarkPart(List<String> parts, String label, String value) {
        if (StringUtils.hasText(value)) parts.add(label + "=" + value.trim());
    }

    private List<String> parseCsvLine(String line) {
        List<String> values = new ArrayList<>();
        StringBuilder current = new StringBuilder();
        boolean inQuote = false;
        for (int i = 0; i < line.length(); i++) {
            char ch = line.charAt(i);
            if (ch == '"') {
                if (inQuote && i + 1 < line.length() && line.charAt(i + 1) == '"') {
                    current.append('"');
                    i++;
                } else {
                    inQuote = !inQuote;
                }
            } else if (ch == ',' && !inQuote) {
                values.add(current.toString());
                current.setLength(0);
            } else {
                current.append(ch);
            }
        }
        values.add(current.toString());
        return values;
    }

    private String canonicalHeader(String objectType, String header) {
        String rawHeader = header == null ? "" : header.trim();
        if (!StringUtils.hasText(rawHeader)) return "";
        List<String> canonicalHeaders = HEADERS.getOrDefault(objectType, List.of());
        if (canonicalHeaders.contains(rawHeader)) return rawHeader;

        String normalizedHeader = normalizeHeaderText(rawHeader);
        if (canonicalHeaders.contains(normalizedHeader)) return normalizedHeader;
        return HEADER_ALIASES.getOrDefault(objectType, Map.of()).getOrDefault(normalizedHeader, rawHeader);
    }

    private static String normalizeHeaderText(String header) {
        return header
            .replace("\uFEFF", "")
            .replace("\u3000", "")
            .replace(" ", "")
            .replace("*", "")
            .replace("（必填）", "")
            .replace("(必填)", "")
            .replace("必填", "")
            .trim()
            .toLowerCase(Locale.ROOT);
    }

    private static Map<String, String> productHeaderAliases() {
        Map<String, String> aliases = new HashMap<>();
        registerHeaderAliases(aliases, "product_specific_code", "产品特定编码", "产品特定码", "产品短码");
        registerHeaderAliases(aliases, "phone_model_code", "手机型号编码", "型号编码");
        registerHeaderAliases(aliases, "color_code", "颜色编码", "颜色码");
        registerHeaderAliases(aliases, "finished_product_code", "成品编码", "SKU关联编码", "SKU编码");
        registerHeaderAliases(aliases, "import_short_code", "导入短码", "外部短码", "短码");
        return Map.copyOf(aliases);
    }

    private static Map<String, String> inventoryHeaderAliases() {
        Map<String, String> aliases = new HashMap<>();
        registerHeaderAliases(aliases, "inventory_code", "新物料编码", "物料编码", "库存编码", "编码", "物料/模具编码");
        registerHeaderAliases(aliases, "inventory_name", "物料名称", "库存名称", "名称", "物料/模具名称");
        registerHeaderAliases(aliases, "inventory_type", "物料类型", "库存类型", "类型");
        registerHeaderAliases(aliases, "specification", "规格", "规格型号", "规格/型号");
        registerHeaderAliases(aliases, "unit", "基本单位", "单位", "库存单位", "计量单位");
        registerHeaderAliases(aliases, "supplier_name", "供应商", "供应商名称");
        registerHeaderAliases(aliases, "unit_cost", "单价", "单位成本", "成本");
        registerHeaderAliases(aliases, "currency_code", "币种", "货币");
        registerHeaderAliases(aliases, "status", "状态");
        registerHeaderAliases(aliases, "remark", "备注");
        registerHeaderAliases(aliases, "ecount_major_code", "一级.大类编码", "一级大类编码", "大类编码");
        registerHeaderAliases(aliases, "ecount_major_name", "物料组", "物料组别", "一级物料组", "一级.名称", "一级名称", "一级.名　称", "大类名称");
        registerHeaderAliases(aliases, "ecount_minor_code", "二级.流水编码", "二级流水编码", "流水编码");
        registerHeaderAliases(aliases, "ecount_minor_name", "二级.名称", "二级名称", "二级.名　称");
        registerHeaderAliases(aliases, "legacy_inventory_code", "旧编码");
        registerHeaderAliases(aliases, "barcode", "条形码", "条码");
        registerHeaderAliases(aliases, "source_created_date", "新增日期");
        return Map.copyOf(aliases);
    }

    private static Map<String, String> processHeaderAliases() {
        Map<String, String> aliases = new HashMap<>();
        registerHeaderAliases(aliases, "product_code", "产品编码", "归属产品编码", "Product编码");
        registerHeaderAliases(aliases, "process_code", "工艺编码", "工序编码", "工艺路线编码", "编码");
        registerHeaderAliases(aliases, "process_name", "工艺名称", "工序名称", "工艺路线名称", "名称");
        registerHeaderAliases(aliases, "process_type", "工艺类型", "工序类型", "类型");
        registerHeaderAliases(aliases, "parent_process_code", "父级工艺编码", "上级工艺编码", "父级工序编码", "上级工序编码");
        registerHeaderAliases(aliases, "sequence_no", "顺序号", "序号", "排序号");
        registerHeaderAliases(aliases, "version_no", "版本号", "版本");
        registerHeaderAliases(aliases, "status", "状态");
        registerHeaderAliases(aliases, "quality_requirement", "质量要求", "品质要求", "质量标准");
        registerHeaderAliases(aliases, "remark", "备注");
        return Map.copyOf(aliases);
    }

    private static Map<String, String> productMoldCodeHeaderAliases() {
        Map<String, String> aliases = new HashMap<>();
        registerHeaderAliases(aliases, "product_code", "产品编码", "归属产品编码", "Product编码");
        registerHeaderAliases(aliases, "mold_name", "mould_name", "模具名称", "模具/产品名称");
        registerHeaderAliases(aliases, "mold_code", "mould_code", "模具编码", "模具/物料编码");
        registerHeaderAliases(aliases, "key_code", "模具关键字", "关键编码", "关键字");
        registerHeaderAliases(aliases, "status", "状态");
        registerHeaderAliases(aliases, "remark", "备注");
        return Map.copyOf(aliases);
    }

    private static void registerHeaderAliases(Map<String, String> aliases, String canonicalHeader, String... displayHeaders) {
        aliases.put(normalizeHeaderText(canonicalHeader), canonicalHeader);
        for (String displayHeader : displayHeaders) {
            aliases.put(normalizeHeaderText(displayHeader), canonicalHeader);
        }
    }

    private byte[] writeWorkbook(String sheetName, List<String> headers, List<Map<String, String>> rows) {
        try (Workbook workbook = new XSSFWorkbook(); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            Sheet sheet = workbook.createSheet(sheetName);
            writeRow(sheet.createRow(0), headers);
            int rowNo = 1;
            for (Map<String, String> data : rows) {
                Row row = sheet.createRow(rowNo++);
                for (int i = 0; i < headers.size(); i++) row.createCell(i).setCellValue(data.getOrDefault(headers.get(i), ""));
            }
            workbook.write(out);
            return out.toByteArray();
        } catch (Exception ex) {
            throw new BusinessException(ErrorCodeConstants.INTERNAL_ERROR, "导出文件生成失败");
        }
    }

    private void writeRow(Row row, List<String> values) {
        for (int i = 0; i < values.size(); i++) row.createCell(i).setCellValue(values.get(i));
    }

    private String cellString(Cell cell) {
        if (cell == null) return "";
        if (cell.getCellType() == CellType.NUMERIC) {
            if (DateUtil.isCellDateFormatted(cell)) return cell.getLocalDateTimeCellValue().toLocalDate().toString();
            double number = cell.getNumericCellValue();
            if (Math.rint(number) == number) return String.valueOf((long) number);
            return BigDecimal.valueOf(number).stripTrailingZeros().toPlainString();
        }
        cell.setCellType(CellType.STRING);
        return cell.getStringCellValue() == null ? "" : cell.getStringCellValue();
    }

    private List<Map<String, String>> exportProducts(String keyword, String status) {
        LambdaQueryWrapper<Product> wrapper = new LambdaQueryWrapper<Product>()
            .eq(Product::getDeletedFlag, 0)
            .eq(StringUtils.hasText(status), Product::getStatus, status)
            .and(StringUtils.hasText(keyword), w -> w.like(Product::getProductCode, keyword).or().like(Product::getProductName, keyword));
        return productRepository.selectList(wrapper).stream().map(product -> {
            Map<String, String> row = new LinkedHashMap<>();
            Product parent = product.getParentProductId() == null ? null : productRepository.selectById(product.getParentProductId());
            row.put("product_code", product.getProductCode());
            row.put("product_name", product.getProductName());
            row.put("product_type", product.getProductType());
            row.put("parent_product_code", parent == null ? "" : parent.getProductCode());
            row.put("series_name", product.getSeriesName());
            row.put("model", product.getModel());
            row.put("color", product.getColor());
            row.put("product_specific_code", product.getProductSpecificCode());
            row.put("phone_model_code", product.getPhoneModelCode());
            row.put("color_code", product.getColorCode());
            row.put("finished_product_code", product.getFinishedProductCode());
            row.put("import_short_code", product.getImportShortCode());
            row.put("version_no", product.getVersionNo());
            row.put("status", product.getStatus());
            row.put("current_stage", product.getCurrentStepNo() == null ? "" : String.valueOf(product.getCurrentStepNo()));
            row.put("remark", product.getRemark());
            return row;
        }).toList();
    }

    private List<Map<String, String>> exportInventories(String keyword, String status) {
        String sql = "select inventory_code, inventory_name, inventory_type, specification, stock_uom, supplier_name, unit_cost, currency_code, status, remark from plm_inventory where deleted_flag = 0";
        List<Object> args = new ArrayList<>();
        if (StringUtils.hasText(keyword)) {
            sql += " and (inventory_code like ? or inventory_name like ?)";
            args.add("%" + keyword + "%");
            args.add("%" + keyword + "%");
        }
        if (StringUtils.hasText(status)) {
            sql += " and status = ?";
            args.add(status);
        }
        sql += " order by updated_at desc";
        return jdbcTemplate.query(sql, (rs, rowNum) -> {
            Map<String, String> row = new LinkedHashMap<>();
            row.put("inventory_code", rs.getString("inventory_code"));
            row.put("inventory_name", rs.getString("inventory_name"));
            row.put("inventory_type", rs.getString("inventory_type"));
            row.put("specification", rs.getString("specification"));
            row.put("unit", rs.getString("stock_uom"));
            row.put("supplier_name", rs.getString("supplier_name"));
            row.put("unit_cost", rs.getString("unit_cost"));
            row.put("currency_code", rs.getString("currency_code"));
            row.put("status", rs.getString("status"));
            row.put("remark", rs.getString("remark"));
            return row;
        }, args.toArray());
    }

    private List<Map<String, String>> exportProcesses(String keyword, String status) {
        LambdaQueryWrapper<ProcessEntity> wrapper = new LambdaQueryWrapper<ProcessEntity>()
            .eq(ProcessEntity::getDeletedFlag, 0)
            .eq(StringUtils.hasText(status), ProcessEntity::getStatus, status)
            .and(StringUtils.hasText(keyword), w -> w.like(ProcessEntity::getProcessCode, keyword).or().like(ProcessEntity::getProcessName, keyword));
        return processRepository.selectList(wrapper).stream().map(process -> {
            Map<String, String> row = new LinkedHashMap<>();
            Product product = productRepository.selectById(process.getProductId());
            ProcessEntity parent = process.getParentProcessId() == null ? null : processRepository.selectById(process.getParentProcessId());
            row.put("product_code", product == null ? "" : product.getProductCode());
            row.put("process_code", process.getProcessCode());
            row.put("process_name", process.getProcessName());
            row.put("process_type", process.getProcessType());
            row.put("parent_process_code", parent == null ? "" : parent.getProcessCode());
            row.put("sequence_no", process.getSequenceNo() == null ? "" : String.valueOf(process.getSequenceNo()));
            row.put("version_no", process.getVersionNo());
            row.put("status", process.getStatus());
            row.put("quality_requirement", process.getQualityRequirement());
            row.put("remark", process.getRemark());
            return row;
        }).toList();
    }

    private List<Map<String, String>> exportProductMoldCodes(String keyword, String status) {
        String sql = """
            select pmc.product_id, p.product_code, p.product_name, pmc.mold_name, pmc.mold_code,
                   pmc.key_code, pmc.status
              from plm_product_mold_code pmc
              join plm_product p on p.product_id = pmc.product_id
             where pmc.deleted_flag = 0
               and p.deleted_flag = 0
            """;
        List<Object> args = new ArrayList<>();
        if (StringUtils.hasText(keyword)) {
            sql += " and (pmc.mold_code like ? or pmc.mold_name like ? or p.product_code like ? or p.product_name like ?)";
            String value = "%" + keyword + "%";
            args.add(value);
            args.add(value);
            args.add(value);
            args.add(value);
        }
        if (StringUtils.hasText(status)) {
            sql += " and pmc.status = ?";
            args.add(status);
        }
        sql += " order by pmc.mold_code";
        return jdbcTemplate.query(sql, (rs, rowNum) -> {
            Map<String, String> row = new LinkedHashMap<>();
            row.put("product_code", rs.getString("product_code"));
            row.put("mold_name", rs.getString("mold_name"));
            row.put("mold_code", rs.getString("mold_code"));
            row.put("key_code", rs.getString("key_code"));
            row.put("status", rs.getString("status"));
            row.put("remark", "");
            return row;
        }, args.toArray());
    }

    private List<Map<String, String>> exportAttachments(String keyword, String status) {
        String sql = """
            select p.product_code, a.file_category, a.original_file_name, a.version_no, a.status, a.remark
            from plm_attachment a
            left join plm_product p on p.product_id = a.owner_object_id and a.owner_object_type = 'Product'
            where a.deleted_flag = 0
            """;
        List<Object> args = new ArrayList<>();
        if (StringUtils.hasText(keyword)) {
            sql += " and (a.original_file_name like ? or a.remark like ? or p.product_code like ?)";
            args.add("%" + keyword + "%");
            args.add("%" + keyword + "%");
            args.add("%" + keyword + "%");
        }
        if (StringUtils.hasText(status)) {
            sql += " and a.status = ?";
            args.add(status);
        }
        sql += " order by a.created_at desc";
        return jdbcTemplate.query(sql, (rs, rowNum) -> {
            Map<String, String> row = new LinkedHashMap<>();
            row.put("owner_object_type", "Product");
            row.put("owner_object_code", rs.getString("product_code"));
            row.put("file_category", rs.getString("file_category"));
            row.put("file_name", rs.getString("original_file_name"));
            row.put("version_no", rs.getString("version_no"));
            row.put("status", rs.getString("status"));
            row.put("legacy_location", "");
            row.put("remark", rs.getString("remark"));
            return row;
        }, args.toArray());
    }

    private Long createBatch(PreviewSession session, String operator) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        try {
            jdbcTemplate.update(connection -> {
                var ps = connection.prepareStatement("""
                    insert into plm_import_batch (object_type, file_name, total_count, success_count, fail_count, status, remark, created_at, created_by, updated_at, updated_by, deleted_flag)
                    values (?, ?, ?, 0, 0, 'in_progress', ?, now(), ?, now(), ?, 0)
                    """, new String[] { "import_batch_id" });
                ps.setString(1, session.objectType);
                ps.setString(2, session.fileName);
                ps.setInt(3, session.rows.size());
                ps.setString(4, "历史存档导入");
                ps.setString(5, operator);
                ps.setString(6, operator);
                return ps;
            }, keyHolder);
        } catch (DataAccessException ex) {
            return null;
        }
        return keyHolder.getKey().longValue();
    }

    private void updateBatch(Long batchId, int success, int fail, String status, String operator) {
        if (batchId == null) return;
        try {
            jdbcTemplate.update("update plm_import_batch set success_count = ?, fail_count = ?, status = ?, updated_at = now(), updated_by = ? where import_batch_id = ?", success, fail, status, operator, batchId);
        } catch (DataAccessException ignored) {
        }
    }

    private void insertDetail(Long batchId, ImportPreviewRowVO row, String status, String message, String operator) {
        if (batchId == null) return;
        try {
            jdbcTemplate.update("""
                insert into plm_import_detail (import_batch_id, row_no, business_key, status, error_message, raw_payload, created_at, created_by, updated_at, updated_by, deleted_flag)
                values (?, ?, ?, ?, ?, ?::jsonb, now(), ?, now(), ?, 0)
                """, batchId, row.getRowNo(), row.getBusinessKey(), status, message, toJson(row.getValues()), operator, operator);
        } catch (DataAccessException ignored) {
        }
    }

    private String toJson(Map<String, String> values) {
        StringBuilder builder = new StringBuilder("{");
        int index = 0;
        for (Map.Entry<String, String> entry : values.entrySet()) {
            if (index++ > 0) builder.append(',');
            builder.append('"').append(escape(entry.getKey())).append("\":\"").append(escape(entry.getValue())).append('"');
        }
        return builder.append('}').toString();
    }

    private String escape(String value) {
        return value == null ? "" : value.replace("\\", "\\\\").replace("\"", "\\\"");
    }

    private boolean isMissingImportMetadataTable(BadSqlGrammarException ex, String tableName) {
        String sqlState = ex.getSQLException() == null ? "" : ex.getSQLException().getSQLState();
        String message = ex.getSQLException() == null ? "" : ex.getSQLException().getMessage();
        return "42P01".equals(sqlState) && message != null && message.contains(tableName);
    }

    private String normalizeType(String objectType) {
        String type = objectType == null ? "" : objectType.trim().toLowerCase(Locale.ROOT);
        if (!OBJECT_TYPES.contains(type)) throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "不支持的导入导出对象：" + objectType);
        return type;
    }

    private ImportPreviewVO toPreviewVO(PreviewSession session) {
        long fail = session.rows.stream().filter(row -> !STATUS_READY.equals(row.getStatus())).count();
        if (session.committedSuccess != null && session.committedFail != null) {
            return ImportPreviewVO.builder()
                .importToken(session.token)
                .objectType(session.objectType)
                .fileName(session.fileName)
                .totalCount(session.rows.size())
                .successCount(session.committedSuccess)
                .failCount(session.committedFail)
                .rows(session.rows)
                .errors(session.errors)
                .build();
        }
        return ImportPreviewVO.builder()
            .importToken(session.token)
            .objectType(session.objectType)
            .fileName(session.fileName)
            .totalCount(session.rows.size())
            .successCount((int) (session.rows.size() - fail))
            .failCount((int) fail)
            .rows(session.rows)
            .errors(session.errors)
            .build();
    }

    private ImportErrorVO error(RowData row, String fieldName, String rawValue, String message) {
        return ImportErrorVO.builder()
            .rowNo(row.rowNo)
            .businessKey(businessKeyByField(row.values))
            .fieldName(fieldName)
            .rawValue(rawValue)
            .errorMessage(message)
            .build();
    }

    private String businessKey(String objectType, Map<String, String> values) {
        return values.getOrDefault(keyField(objectType), "");
    }

    private String businessKeyByField(Map<String, String> values) {
        for (String key : List.of("product_code", "inventory_code", "process_code", "mold_code", "file_name")) {
            if (StringUtils.hasText(values.get(key))) return values.get(key);
        }
        return "";
    }

    private String keyField(String objectType) {
        return switch (objectType) {
            case "product" -> "product_code";
            case "inventory" -> "inventory_code";
            case "process" -> "process_code";
            case "product_mold_code" -> "mold_code";
            default -> "file_name";
        };
    }

    private CodeDetection detectImportCode(String rawCode) {
        String code = normalizeBusinessCode(rawCode);
        if (!StringUtils.hasText(code)) {
            return CodeDetection.empty();
        }
        try {
            if (code.startsWith(ProductBusinessCodeGenerator.PRODUCT_STATE_PREFIX)) {
                ProductBusinessCodeGenerator.ProductStateCodeParts parts = businessCodeGenerator.parseProductStateCode(code);
                Product matched = parts.finishedProduct() ? findProductByFinishedProductCode(code) : null;
                return new CodeDetection(
                    code,
                    parts.finishedProduct() ? "finished_product_code" : "semi_finished_product_code",
                    matched == null ? "" : matched.getProductCode(),
                    parts.finishedProduct() ? code : "",
                    matched == null ? "create_candidate" : "matched",
                    parts.finishedProduct() ? "finished product code" : "semi-finished operation code"
                );
            }
            if (isLikelyMoldCode(code)) {
                ProductBusinessCodeGenerator.MoldCodeParts parts = businessCodeGenerator.parseMoldCode(code, null, List.of(), null);
                return new CodeDetection(code, "mold_code", "", "", "manual_confirm",
                    "mold:" + parts.productSpecificCode() + "/" + nullToEmpty(parts.materialCode()) + "/" + nullToEmpty(parts.phoneModelCode()));
            }
            if (code.length() == 5) {
                Product matched = findProductByImportShortCode(code);
                return new CodeDetection(code, "product_short_code", matched == null ? "" : matched.getProductCode(), "",
                    matched == null ? "create_candidate" : "matched", "5-char product short code");
            }
            if (code.length() == 9) {
                Product matched = findProductByImportShortCode(code);
                return new CodeDetection(code, "model_variant_short_code", matched == null ? "" : matched.getProductCode(),
                    matched == null ? "" : nullToEmpty(matched.getFinishedProductCode()),
                    matched == null ? "create_candidate" : "matched", "9-char model/SKU short code");
            }
            return new CodeDetection(code, "unknown_code", "", "", "manual_confirm", "code is not M/N, 5-char, or 9-char");
        } catch (BusinessException ex) {
            return new CodeDetection(code, "invalid_code", "", "", "error", ex.getMessage());
        }
    }

    private boolean isLikelyMoldCode(String code) {
        return StringUtils.hasText(code) && code.matches("[A-Z]{3}\\d{2,}");
    }

    private Product findProductByCode(String code) {
        if (!StringUtils.hasText(code)) return null;
        return productRepository.selectOne(new LambdaQueryWrapper<Product>()
            .eq(Product::getProductCode, code)
            .eq(Product::getDeletedFlag, 0)
            .last("limit 1"));
    }

    private Product findProductByFinishedProductCode(String code) {
        if (!StringUtils.hasText(code)) return null;
        return productRepository.selectOne(new LambdaQueryWrapper<Product>()
            .eq(Product::getFinishedProductCode, normalizeBusinessCode(code))
            .eq(Product::getDeletedFlag, 0)
            .last("limit 1"));
    }

    private Product findProductByImportShortCode(String code) {
        if (!StringUtils.hasText(code)) return null;
        return productRepository.selectOne(new LambdaQueryWrapper<Product>()
            .eq(Product::getImportShortCode, normalizeBusinessCode(code))
            .eq(Product::getDeletedFlag, 0)
            .last("limit 1"));
    }

    private Product findProductByProductSpecificCode(String code) {
        if (!StringUtils.hasText(code)) return null;
        return productRepository.selectOne(new LambdaQueryWrapper<Product>()
            .eq(Product::getProductSpecificCode, normalizeBusinessCode(code))
            .eq(Product::getDeletedFlag, 0)
            .last("limit 1"));
    }

    private ProcessProductResolution resolveProductForProcessImport(Map<String, String> values, boolean allowAutoCreateSku, String operator) {
        String productCode = normalizeBusinessCode(values.get("product_code"));
        Product product = findProductByCode(productCode);
        if (product != null) return new ProcessProductResolution(product, parseLegacyProcessCode(productCode), false);

        FullProductStateCode fullCode = parseFullProductStateCode(productCode);
        if (fullCode.valid()) {
            Product matched = fullCode.finishedProduct() ? findProductByFinishedProductCode(productCode) : null;
            if (matched != null) return new ProcessProductResolution(matched, fullCode.toLegacyProcessCode(), false);
            Product parent = findProductByProductSpecificCode(fullCode.productSpecificCode());
            if (parent != null && fullCode.finishedProduct() && allowAutoCreateSku) {
                Product sku = createProcessImportSku(productCode, parent, fullCode, operator);
                return new ProcessProductResolution(sku, fullCode.toLegacyProcessCode(), true);
            }
            if (parent != null) return new ProcessProductResolution(parent, fullCode.toLegacyProcessCode(), false);
        }

        Product shortCodeProduct = findProductByImportShortCode(productCode);
        if (shortCodeProduct != null) return new ProcessProductResolution(shortCodeProduct, LegacyProcessCode.empty(), false);
        if (productCode.length() == 9) {
            Product parent = findProductByImportShortCode(productCode.substring(0, 5));
            if (parent != null && allowAutoCreateSku) {
                Product sku = createProcessImportSku(productCode, parent, FullProductStateCode.empty(), operator);
                return new ProcessProductResolution(sku, LegacyProcessCode.empty(), true);
            }
            if (parent != null) return new ProcessProductResolution(parent, LegacyProcessCode.empty(), false);
        }

        LegacyProcessCode legacyCode = parseLegacyProcessCode(productCode);
        if (legacyCode != LegacyProcessCode.empty()) {
            Product parent = findProductByProductSpecificCode(legacyCode.productSpecificCode());
            if (parent != null) return new ProcessProductResolution(parent, legacyCode, false);
        }
        return new ProcessProductResolution(null, legacyCode, false);
    }

    private Product createProcessImportSku(String productCode, Product parent, FullProductStateCode fullCode, String operator) {
        Product sku = new Product();
        sku.setParentProductId(parent.getProductId());
        sku.setProductCode(productCode);
        sku.setProductName(routeProductName(parent) + " " + productCode);
        sku.setProductType("sku");
        sku.setProductSpecificCode(firstText(fullCode.productSpecificCode(), parent.getProductSpecificCode()));
        sku.setPhoneModelCode(firstText(fullCode.phoneModelCode(), parent.getPhoneModelCode()));
        sku.setColorCode(firstText(fullCode.colorCode(), parent.getColorCode()));
        if (fullCode.finishedProduct()) {
            sku.setFinishedProductCode(productCode);
        } else if (productCode.length() == 9) {
            sku.setImportShortCode(productCode);
        }
        sku.setVersionNo("V1");
        sku.setStatus("archived");
        sku.setCurrentStepNo(MODEL_VARIANT_TERMINAL_STEP_NO);
        sku.setLockStatus("unlocked");
        sku.setRemark(appendHistoryRemark("\u5de5\u827a\u5bfc\u5165\u81ea\u52a8\u521b\u5efaSKU"));
        LocalDateTime now = LocalDateTime.now();
        sku.setCreatedAt(now);
        sku.setCreatedBy(operator);
        sku.setUpdatedAt(now);
        sku.setUpdatedBy(operator);
        sku.setArchivedAt(now);
        sku.setArchivedBy("history-import");
        sku.setDeletedFlag(0);
        productRepository.insert(sku);
        return sku;
    }

    private FullProductStateCode parseFullProductStateCode(String code) {
        String normalized = normalizeBusinessCode(code);
        if (!normalized.startsWith(ProductBusinessCodeGenerator.PRODUCT_STATE_PREFIX) || normalized.length() < 13) {
            return FullProductStateCode.empty();
        }
        try {
            ProductBusinessCodeGenerator.ProductStateCodeParts parts = businessCodeGenerator.parseProductStateCode(normalized);
            return new FullProductStateCode(
                true,
                normalized,
                parts.productSpecificCode(),
                parts.operationCode(),
                parts.phoneModelCode(),
                parts.colorCode(),
                parts.finishedProduct()
            );
        } catch (BusinessException ex) {
            return FullProductStateCode.empty();
        }
    }

    private LegacyProcessCode parseLegacyProcessCode(String code) {
        String normalized = normalizeBusinessCode(code);
        if (!normalized.startsWith(ProductBusinessCodeGenerator.PRODUCT_STATE_PREFIX) || normalized.length() < 6 || normalized.length() >= 13) {
            return LegacyProcessCode.empty();
        }
        String operationCode = normalized.substring(normalized.length() - 4);
        if (!operationCode.matches("\\d{4}")) return LegacyProcessCode.empty();
        String productSpecificCode = normalized.substring(1, normalized.length() - 4);
        if (!StringUtils.hasText(productSpecificCode)) return LegacyProcessCode.empty();
        return new LegacyProcessCode(
            normalized,
            productSpecificCode,
            operationCode,
            ProductBusinessCodeGenerator.DEFAULT_FINAL_OPERATION_CODE.equals(operationCode)
        );
    }

    private ProcessEntity findProcessByCode(String code) {
        if (!StringUtils.hasText(code)) return null;
        return processRepository.selectOne(new LambdaQueryWrapper<ProcessEntity>()
            .eq(ProcessEntity::getProcessCode, code)
            .eq(ProcessEntity::getDeletedFlag, 0)
            .last("limit 1"));
    }

    private boolean isBusinessOperationCodeAvailable(String code, Long currentProcessId) {
        if (!StringUtils.hasText(code)) return false;
        ProcessEntity existing = processRepository.selectOne(new LambdaQueryWrapper<ProcessEntity>()
            .eq(ProcessEntity::getBusinessOperationCode, normalizeBusinessCode(code))
            .eq(ProcessEntity::getDeletedFlag, 0)
            .last("limit 1"));
        return existing == null || (currentProcessId != null && currentProcessId.equals(existing.getProcessId()));
    }

    private boolean existsProductCode(String code) {
        return findProductByCode(code) != null;
    }

    private boolean existsProcessCode(String code) {
        return findProcessByCode(code) != null;
    }

    private boolean existsInventoryCode(String code) {
        if (!StringUtils.hasText(code)) return false;
        Integer count = jdbcTemplate.queryForObject("select count(*) from plm_inventory where inventory_code = ? and deleted_flag = 0", Integer.class, code);
        return count != null && count > 0;
    }

    private void parseDecimal(String value, RowData row, String fieldName, List<ImportErrorVO> errors) {
        if (!StringUtils.hasText(value)) return;
        try { new BigDecimal(value); } catch (Exception ex) { errors.add(error(row, fieldName, value, "数字格式不正确")); }
    }

    private void parseInteger(String value, RowData row, String fieldName, List<ImportErrorVO> errors) {
        if (!StringUtils.hasText(value)) return;
        try { Integer.parseInt(value); } catch (Exception ex) { errors.add(error(row, fieldName, value, "整数格式不正确")); }
    }

    private BigDecimal decimalOrNull(String value) {
        return StringUtils.hasText(value) ? new BigDecimal(value) : null;
    }

    private String normalizeBusinessCode(String value) {
        return StringUtils.hasText(value) ? value.trim().toUpperCase(Locale.ROOT) : "";
    }

    private String normalizeGroupCode(String value) {
        return StringUtils.hasText(value) ? value.trim().toUpperCase(Locale.ROOT) : "";
    }

    private String trimToEmpty(String value) {
        return StringUtils.hasText(value) ? value.trim() : "";
    }

    private String firstText(String... values) {
        for (String value : values) {
            if (StringUtils.hasText(value)) {
                return value;
            }
        }
        return "";
    }

    private String nullToEmpty(String value) {
        return value == null ? "" : value;
    }

    private boolean equalsIgnoreCase(String left, String right) {
        return StringUtils.hasText(left) && StringUtils.hasText(right) && left.trim().equalsIgnoreCase(right.trim());
    }

    private String supplierNameOrDefault(String supplierName) {
        return StringUtils.hasText(supplierName) ? supplierName.trim() : DEFAULT_SUPPLIER_NAME;
    }

    private Integer integerOrNull(String value) {
        return StringUtils.hasText(value) ? Integer.parseInt(value) : null;
    }

    private String appendHistoryRemark(String remark) {
        return (StringUtils.hasText(remark) ? remark + "；" : "") + "历史存档导入";
    }

    private String currentUserName() {
        return CurrentUserContext.get().map(CurrentUser::displayName).filter(StringUtils::hasText).orElse("system");
    }

    private void writeLog(String action, String businessType, String businessId, String businessName, HttpServletRequest request) {
        try {
            operationLogService.logSuccess(OperationLogCreateCommand.builder()
                .action(action)
                .businessType("IMPORT_EXPORT")
                .businessId(businessId)
                .businessCode(businessType)
                .businessName(businessName)
                .detailJson("{\"objectType\":\"" + businessType + "\"}")
                .request(request)
                .build());
        } catch (RuntimeException ignored) {
            // Import/export commit must not fail after the business rows have been processed just because audit logging is unavailable.
        }
    }

    private record HeaderLayout(Map<Integer, String> headers, int firstDataRowIndex) {}

    private record ProcessProductResolution(Product product, LegacyProcessCode legacyCode, boolean autoCreatedSku) {}

    private record LegacyProcessCode(String normalizedCode, String productSpecificCode, String operationCode, boolean finishedProduct) {
        private static final LegacyProcessCode EMPTY = new LegacyProcessCode("", "", "", false);

        private static LegacyProcessCode empty() {
            return EMPTY;
        }
    }

    private record FullProductStateCode(boolean valid, String normalizedCode, String productSpecificCode, String operationCode,
                                        String phoneModelCode, String colorCode, boolean finishedProduct) {
        private static final FullProductStateCode EMPTY = new FullProductStateCode(false, "", "", "", "", "", false);

        private static FullProductStateCode empty() {
            return EMPTY;
        }

        private LegacyProcessCode toLegacyProcessCode() {
            if (!valid) return LegacyProcessCode.empty();
            return new LegacyProcessCode(normalizedCode, productSpecificCode, operationCode, finishedProduct);
        }
    }

    private record RowData(Integer rowNo, Map<String, String> values) {}

    private record CodeDetection(String normalizedCode, String objectType, String matchedProductCode,
                                 String matchedFinishedCode, String matchStatus, String matchMessage) {
        private static CodeDetection empty() {
            return new CodeDetection("", "", "", "", "", "");
        }
    }

    private static class PreviewSession {
        private final String token;
        private final String objectType;
        private final String fileName;
        private final List<ImportPreviewRowVO> rows;
        private final List<ImportErrorVO> errors;
        private final Integer committedSuccess;
        private final Integer committedFail;

        PreviewSession(String token, String objectType, String fileName, List<ImportPreviewRowVO> rows, List<ImportErrorVO> errors, Integer committedSuccess, Integer committedFail) {
            this.token = token;
            this.objectType = objectType;
            this.fileName = fileName;
            this.rows = rows;
            this.errors = errors;
            this.committedSuccess = committedSuccess;
            this.committedFail = committedFail;
        }

        PreviewSession withCommittedCounts(int success, int fail) {
            return new PreviewSession(token, objectType, fileName, rows, errors, success, fail);
        }
    }
}
