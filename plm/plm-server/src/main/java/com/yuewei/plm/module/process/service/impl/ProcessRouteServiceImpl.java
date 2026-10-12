package com.yuewei.plm.module.process.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.common.security.CurrentUserContext;
import com.yuewei.plm.common.util.ProductBusinessCodeGenerator;
import com.yuewei.plm.module.operationlog.constant.OperationActionConstants;
import com.yuewei.plm.module.operationlog.service.OperationLogCreateCommand;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.bom.entity.ProductBom;
import com.yuewei.plm.module.bom.entity.ProductBomRoute;
import com.yuewei.plm.module.bom.repository.ProductBomRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteRepository;
import com.yuewei.plm.module.process.dto.ProcessOperationDTO;
import com.yuewei.plm.module.process.dto.ProcessRouteSaveDTO;
import com.yuewei.plm.module.process.entity.ProcessEntity;
import com.yuewei.plm.module.process.repository.ProcessRepository;
import com.yuewei.plm.module.process.service.ProcessRouteNamingRules;
import com.yuewei.plm.module.process.service.ProcessRouteService;
import com.yuewei.plm.module.process.service.ProcessRouteTemplateService;
import com.yuewei.plm.module.process.vo.ProcessOperationVO;
import com.yuewei.plm.module.process.vo.ProcessRouteTemplateVO;
import com.yuewei.plm.module.process.vo.ProcessRouteVO;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import jakarta.servlet.http.HttpServletRequest;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

@Service
@RequiredArgsConstructor
public class ProcessRouteServiceImpl implements ProcessRouteService {

    private static final String TYPE_ROUTING = "routing";
    private static final String TYPE_OPERATION = "operation";
    private static final String TYPE_OPERATION_MASTER = "operation_master";
    private static final String STATUS_DRAFT = "draft";
    private static final String STATUS_CONFIRMED = "confirmed";
    private static final String STATUS_LOCKED = "locked";
    private static final int ROUTE_CODE_MAX_LENGTH = 20;
    private static final int PROCESS_CODE_MAX_LENGTH = 64;
    private static final String OPERATION_SOURCE_IMPORTED = "imported_snapshot";
    private static final Set<String> FORBIDDEN_MATERIAL_STATUS_CODES = Set.of("40", "FINISHED", "FINISHED_PRODUCT", "成品");
    private static final Map<String, String> DEFAULT_OPERATION_CRAFT_CODES = Map.ofEntries(
        Map.entry("PROC_INJECTION", "1010"),
        Map.entry("PROC_TPU_FORMING", "1010"),
        Map.entry("PROC_BASE_FORMING", "1010"),
        Map.entry("PROC_PUNCHING", "1020"),
        Map.entry("PROC_PRINTING", "1020"),
        Map.entry("PROC_COATING", "1020"),
        Map.entry("PROC_SPRAYING", "1020"),
        Map.entry("PROC_ASSEMBLY", "4030"),
        Map.entry("PROC_PACKING", "4030"),
        Map.entry("PROC_CNC", "1020"),
        Map.entry("PROC_MAGNET", "1020"),
        Map.entry("PROC_MAGNET_ATTACH", "1020")
    );

    private final ProductRepository productRepository;
    private final ProcessRepository processRepository;
    private final ProductBomRepository productBomRepository;
    private final ProductBomRouteRepository productBomRouteRepository;
    private final OperationLogService operationLogService;
    private final ProcessRouteTemplateService processRouteTemplateService;
    private final ObjectMapper objectMapper;
    private final ProductBusinessCodeGenerator businessCodeGenerator = new ProductBusinessCodeGenerator();

    @Override
    public List<ProcessRouteVO> listByProject(Long projectId) {
        getProductOrThrow(projectId);
        return processRepository.selectList(new LambdaQueryWrapper<ProcessEntity>()
                .eq(ProcessEntity::getProductId, projectId)
                .eq(ProcessEntity::getProcessType, TYPE_ROUTING)
                .eq(ProcessEntity::getDeletedFlag, 0)
            .orderByDesc(ProcessEntity::getProcessId))
            .stream()
            .map(route -> toRouteVO(route, listOperations(route.getProcessId())))
            .toList();
    }

    @Override
    public ProcessRouteVO getById(Long processId) {
        ProcessEntity route = getRouteOrThrow(processId);
        return toRouteVO(route, listOperations(processId));
    }

    @Override
    @Transactional
    public ProcessRouteVO create(Long projectId, ProcessRouteSaveDTO dto, HttpServletRequest request) {
        Product product = getProductOrThrow(projectId);
        ProcessRouteTemplateVO template = resolveTemplate(dto);
        List<ProcessOperationDTO> operations = resolveOperations(dto, template);
        validateOperations(operations);
        validateCodeGenerationContext(product, operations);
        LocalDateTime now = LocalDateTime.now();
        String operator = currentUserName();
        ProcessEntity route = new ProcessEntity();
        route.setProductId(projectId);
        route.setProcessCode(buildProcessCode(product, dto));
        route.setProcessName(ProcessRouteNamingRules.routeName(dto.getProcessName(), product));
        route.setProcessType(TYPE_ROUTING);
        route.setVersionNo(dto.getVersionNo());
        route.setStatus(Boolean.TRUE.equals(dto.getFinalSelected()) ? STATUS_CONFIRMED : STATUS_DRAFT);
        route.setProcessParamJson(buildRouteMetadataJson(dto, template));
        route.setRemark(dto.getRemark());
        ensureProcessCodeAvailable(route.getProcessCode(), null);
        fillCreateAudit(route, now, operator);
        processRepository.insert(route);
        rebuildOperations(product, route, operations, now, operator);
        writeLog(OperationActionConstants.PROCESS_ROUTE_CREATE, route, product, "{\"action\":\"create\"}", request);
        return getById(route.getProcessId());
    }

    @Override
    @Transactional
    public ProcessRouteVO update(Long processId, ProcessRouteSaveDTO dto, HttpServletRequest request) {
        ProcessEntity route = requireEditableRoute(processId);
        Product product = getProductOrThrow(route.getProductId());
        ProcessRouteTemplateVO template = resolveTemplate(dto);
        List<ProcessOperationDTO> operations = resolveOperations(dto, template);
        validateOperations(operations);
        validateCodeGenerationContext(product, operations);
        String processCode = buildProcessCode(product, dto);
        ensureProcessCodeAvailable(processCode, processId);
        route.setProcessName(ProcessRouteNamingRules.routeName(dto.getProcessName(), product));
        route.setProcessCode(processCode);
        route.setVersionNo(dto.getVersionNo());
        if (Boolean.TRUE.equals(dto.getFinalSelected())) {
            route.setStatus(STATUS_CONFIRMED);
        }
        route.setProcessParamJson(buildRouteMetadataJson(dto, template));
        route.setRemark(dto.getRemark());
        fillUpdateAudit(route);
        processRepository.updateById(route);
        softDeleteOperations(processId);
        rebuildOperations(product, route, operations, LocalDateTime.now(), currentUserName());
        writeLog(OperationActionConstants.PROCESS_ROUTE_UPDATE, route, product, "{\"action\":\"update\"}", request);
        return getById(processId);
    }

    @Override
    @Transactional
    public void deleteVersion(Long processId, HttpServletRequest request) {
        ProcessEntity route = requireDeletableRoute(processId);
        Product product = getProductOrThrow(route.getProductId());
        LocalDateTime now = LocalDateTime.now();
        String operator = currentUserName();

        processRepository.update(null, new UpdateWrapper<ProcessEntity>()
            .set("deleted_flag", 1)
            .set("updated_at", now)
            .set("updated_by", operator)
            .eq("process_id", processId)
            .eq("process_type", TYPE_ROUTING)
            .eq("deleted_flag", 0));
        processRepository.update(null, new UpdateWrapper<ProcessEntity>()
            .set("deleted_flag", 1)
            .set("updated_at", now)
            .set("updated_by", operator)
            .eq("parent_process_id", processId)
            .eq("process_type", TYPE_OPERATION)
            .eq("deleted_flag", 0));

        writeLog(OperationActionConstants.PROCESS_ROUTE_DELETE, route, product,
            "{\"action\":\"delete_version\",\"versionNo\":\"" + route.getVersionNo() + "\"}", request);
    }

    @Override
    @Transactional
    public ProcessRouteVO freeze(Long processId, HttpServletRequest request) {
        ProcessEntity route = requireEditableRoute(processId);
        Product product = getProductOrThrow(route.getProductId());
        List<ProcessOperationVO> operations = listOperations(processId);
        if (operations.isEmpty()) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "工艺路线至少需要1道工序才能冻结");
        }
        route.setStatus(STATUS_LOCKED);
        route.setFrozenAt(LocalDateTime.now());
        route.setFrozenBy(currentUserName());
        fillUpdateAudit(route);
        processRepository.updateById(route);
        processRepository.selectList(new LambdaQueryWrapper<ProcessEntity>()
                .eq(ProcessEntity::getParentProcessId, processId)
                .eq(ProcessEntity::getProcessType, TYPE_OPERATION)
                .eq(ProcessEntity::getDeletedFlag, 0))
            .forEach(operation -> {
                operation.setStatus(STATUS_LOCKED);
                fillUpdateAudit(operation);
                processRepository.updateById(operation);
            });
        writeLog(OperationActionConstants.PROCESS_ROUTE_FREEZE, route, product, "{\"action\":\"freeze\"}", request);
        return getById(processId);
    }

    private Product getProductOrThrow(Long projectId) {
        Product product = productRepository.selectById(projectId);
        if (product == null || Integer.valueOf(1).equals(product.getDeletedFlag())) {
            throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "项目不存在");
        }
        return product;
    }

    private ProcessEntity getRouteOrThrow(Long processId) {
        ProcessEntity route = processRepository.selectById(processId);
        if (route == null || Integer.valueOf(1).equals(route.getDeletedFlag()) || !TYPE_ROUTING.equals(route.getProcessType())) {
            throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "工艺路线不存在");
        }
        return route;
    }

    private ProcessEntity requireEditableRoute(Long processId) {
        ProcessEntity route = getRouteOrThrow(processId);
        if (!Set.of(STATUS_DRAFT, STATUS_CONFIRMED).contains(route.getStatus())) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR,
                "已锁定或已归档工艺路线不能直接编辑，请基于当前路线创建新版本");
        }
        return route;
    }

    private ProcessEntity requireDeletableRoute(Long processId) {
        ProcessEntity route = getRouteOrThrow(processId);
        if (!Set.of(STATUS_DRAFT, STATUS_CONFIRMED).contains(route.getStatus())) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR,
                "已锁定或已归档工艺路线不能直接删除，请先创建新版本或走变更流程");
        }
        List<ProductBomRoute> references = productBomRouteRepository.selectList(new LambdaQueryWrapper<ProductBomRoute>()
            .eq(ProductBomRoute::getProcessId, processId)
            .eq(ProductBomRoute::getDeletedFlag, 0));
        if (references != null && !references.isEmpty()) {
            Set<Long> bomIds = references.stream()
                .map(ProductBomRoute::getProductBomId)
                .filter(java.util.Objects::nonNull)
                .collect(java.util.stream.Collectors.toSet());
            if (!bomIds.isEmpty()) {
                List<ProductBom> activeBoms = productBomRepository.selectList(new LambdaQueryWrapper<ProductBom>()
                    .in(ProductBom::getProductBomId, bomIds)
                    .eq(ProductBom::getDeletedFlag, 0));
                if (activeBoms != null && !activeBoms.isEmpty()) {
                    throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "工艺路线仍被有效 BOM 版本关联，请先删除或调整 BOM 关联");
                }
            }
        }
        return route;
    }

    private List<ProcessOperationVO> listOperations(Long processId) {
        return processRepository.selectList(new LambdaQueryWrapper<ProcessEntity>()
                .eq(ProcessEntity::getParentProcessId, processId)
                .eq(ProcessEntity::getProcessType, TYPE_OPERATION)
                .eq(ProcessEntity::getDeletedFlag, 0)
                .orderByAsc(ProcessEntity::getSequenceNo))
            .stream()
            .map(ProcessOperationVO::from)
            .toList();
    }

    private ProcessRouteTemplateVO resolveTemplate(ProcessRouteSaveDTO dto) {
        if (!StringUtils.hasText(dto.getRouteTemplateCode())) {
            return null;
        }
        return processRouteTemplateService.getPublishedTemplate(dto.getRouteTemplateCode(), dto.getRouteTemplateVersion());
    }

    private List<ProcessOperationDTO> resolveOperations(ProcessRouteSaveDTO dto, ProcessRouteTemplateVO template) {
        if (dto.getOperations() != null && !dto.getOperations().isEmpty()) {
            return dto.getOperations();
        }
        if (template == null || !Boolean.TRUE.equals(dto.getCopyTemplateOperations())) {
            return dto.getOperations();
        }
        return template.getOperations().stream()
            .map(operation -> {
                ProcessOperationDTO target = new ProcessOperationDTO();
                target.setOperationCode(operation.getOperationCode());
                target.setOperationMasterProcessId(operation.getOperationMasterProcessId());
                target.setOperationCraftCode(operation.getOperationCraftCode());
                target.setMaterialStatusCode(operation.getMaterialStatusCode());
                target.setFinishedProductFlag(operation.getFinishedProductFlag());
                target.setBusinessOperationCode(operation.getBusinessOperationCode());
                target.setBusinessOperationCodeManualFlag(operation.getBusinessOperationCodeManualFlag());
                target.setSequenceNo(operation.getSequenceNo());
                target.setProcessName(operation.getProcessName());
                target.setProcessParamJson(operation.getProcessParamJson());
                target.setStandardTimeMins(operation.getStandardTimeMins());
                target.setQualityRequirement(operation.getQualityRequirement());
                target.setRemark(operation.getRemark());
                return target;
            })
            .toList();
    }

    private String buildProcessCode(Product product, ProcessRouteSaveDTO dto) {
        if (!StringUtils.hasText(product.getProductCode())) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "productCode is required before creating process route");
        }
        return compactGeneratedCode(
            ProcessRouteNamingRules.manualRouteCode(product, dto.getRouteTemplateCode(), dto.getVersionNo()),
            ROUTE_CODE_MAX_LENGTH
        );
    }

    private void ensureProcessCodeAvailable(String processCode, Long excludedProcessId) {
        LambdaQueryWrapper<ProcessEntity> wrapper = new LambdaQueryWrapper<ProcessEntity>()
            .eq(ProcessEntity::getProcessCode, processCode)
            .eq(ProcessEntity::getDeletedFlag, 0);
        if (excludedProcessId != null) {
            wrapper.ne(ProcessEntity::getProcessId, excludedProcessId);
        }
        Long count = processRepository.selectCount(wrapper);
        if (count != null && count > 0) {
            throw new BusinessException(ErrorCodeConstants.CODE_CONFLICT, "processCode already exists: " + processCode);
        }
    }

    private String buildRouteMetadataJson(ProcessRouteSaveDTO dto, ProcessRouteTemplateVO template) {
        Map<String, Object> metadata = new LinkedHashMap<>();
        if (template != null) {
            metadata.put("routeTemplateCode", template.getRouteTemplateCode());
            metadata.put("routeTemplateName", template.getRouteTemplateName());
            metadata.put("routeTemplateVersion", template.getVersionNo());
        } else if (StringUtils.hasText(dto.getRouteTemplateCode())) {
            metadata.put("routeTemplateCode", dto.getRouteTemplateCode());
            metadata.put("routeTemplateVersion", dto.getRouteTemplateVersion());
        }
        metadata.put("copyTemplateOperations", Boolean.TRUE.equals(dto.getCopyTemplateOperations()));
        metadata.put("applicableModel", dto.getApplicableModel());
        metadata.put("applicableColor", dto.getApplicableColor());
        metadata.put("linkedBomVersionNo", dto.getLinkedBomVersionNo());
        metadata.put("finalSelected", Boolean.TRUE.equals(dto.getFinalSelected()));
        try {
            return objectMapper.writeValueAsString(metadata);
        } catch (Exception ex) {
            throw new BusinessException(ErrorCodeConstants.INTERNAL_ERROR, "failed to build process route metadata");
        }
    }

    @SuppressWarnings("unchecked")
    private ProcessRouteVO toRouteVO(ProcessEntity route, List<ProcessOperationVO> operations) {
        ProcessRouteVO vo = ProcessRouteVO.from(route, operations);
        if (!StringUtils.hasText(route.getProcessParamJson())) {
            return vo;
        }
        try {
            Map<String, Object> metadata = objectMapper.readValue(route.getProcessParamJson(), Map.class);
            vo.setRouteTemplateCode(asString(metadata.get("routeTemplateCode")));
            vo.setRouteTemplateVersion(asString(metadata.get("routeTemplateVersion")));
            vo.setApplicableModel(asString(metadata.get("applicableModel")));
            vo.setApplicableColor(asString(metadata.get("applicableColor")));
            vo.setLinkedBomVersionNo(asString(metadata.get("linkedBomVersionNo")));
            vo.setFinalSelected(Boolean.TRUE.equals(metadata.get("finalSelected")));
        } catch (Exception ignored) {
            vo.setFinalSelected(false);
        }
        return vo;
    }

    private String asString(Object value) {
        return value == null ? null : String.valueOf(value);
    }

    private void validateOperations(List<ProcessOperationDTO> operations) {
        if (operations == null || operations.isEmpty()) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "工艺路线至少需要1道工序");
        }
        Set<Integer> sequenceNos = new HashSet<>();
        for (ProcessOperationDTO operation : operations) {
            if (operation.getSequenceNo() == null || operation.getSequenceNo() <= 0) {
                throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "工序顺序必须大于0");
            }
            if (!sequenceNos.add(operation.getSequenceNo())) {
                throw new BusinessException(ErrorCodeConstants.CODE_CONFLICT, "同一工艺路线下工序顺序不能重复");
            }
            boolean importedSnapshot = OPERATION_SOURCE_IMPORTED.equals(operation.getOperationSource());
            ProcessEntity master = resolveOperationMaster(operation.getOperationMasterProcessId());
            resolveOperationName(operation, master);
            validateOperationCraftCode(resolveOperationCraftCode(operation, master));
            if (master == null && !importedSnapshot
                && !StringUtils.hasText(operation.getQualityRequirement())) {
                throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "工序名称和质量要求不能为空");
            }
            validateMaterialStatusCode(operation.getMaterialStatusCode());
            validateBusinessOperationCode(operation.getBusinessOperationCode());
            if (StringUtils.hasText(operation.getProcessParamJson())) {
                try {
                    if (!objectMapper.readTree(operation.getProcessParamJson()).isObject()) {
                        throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "process params must be a JSON object");
                    }
                } catch (Exception ex) {
                    throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "工艺参数必须是合法JSON");
                }
            }
        }
    }

    private void rebuildOperations(Product product, ProcessEntity route, List<ProcessOperationDTO> operations,
                                   LocalDateTime now, String operator) {
        Set<String> businessOperationCodes = new HashSet<>();
        for (ProcessOperationDTO dto : operations) {
            ProcessEntity master = resolveOperationMaster(dto.getOperationMasterProcessId());
            String operationCode = resolveOperationCode(dto, master);
            String operationName = resolveOperationName(dto, master);
            String operationCraftCode = resolveOperationCraftCode(dto, master);
            String materialStatusCode = normalizeCode(dto.getMaterialStatusCode());
            CodeGenerationContext codeContext = resolveCodeGenerationContext(product, dto, operationCraftCode);
            String businessOperationCode = resolveBusinessOperationCode(dto, operationCraftCode, codeContext);
            String generatedFinishedProductCode = resolveGeneratedFinishedProductCode(operationCraftCode, businessOperationCode);
            if (StringUtils.hasText(businessOperationCode)) {
                if (!businessOperationCodes.add(businessOperationCode)) {
                    throw new BusinessException(ErrorCodeConstants.CODE_CONFLICT, "businessOperationCode duplicated in route: " + businessOperationCode);
                }
                ensureBusinessOperationCodeAvailable(route.getProcessId(), businessOperationCode);
            }
            ProcessEntity operation = new ProcessEntity();
            operation.setParentProcessId(route.getProcessId());
            operation.setProductId(route.getProductId());
            operation.setProcessCode(buildRouteOperationProcessCode(route, dto, operationCode));
            operation.setOperationMasterProcessId(master == null ? null : master.getProcessId());
            operation.setProcessName(operationName);
            operation.setProcessType(TYPE_OPERATION);
            operation.setOperationCraftCode(operationCraftCode);
            operation.setMaterialStatusCode(materialStatusCode);
            operation.setFinishedProductFlag(Boolean.TRUE.equals(dto.getFinishedProductFlag()));
            operation.setBusinessOperationCode(businessOperationCode);
            operation.setBusinessOperationCodeManualFlag(Boolean.TRUE.equals(dto.getBusinessOperationCodeManualFlag())
                && StringUtils.hasText(businessOperationCode));
            operation.setProductSpecificCode(codeContext.productSpecificCode());
            operation.setPhoneModelCode(codeContext.phoneModelCode());
            operation.setColorCode(codeContext.colorCode());
            operation.setGeneratedFinishedProductCode(generatedFinishedProductCode);
            operation.setCodeGenerationContext(codeContext.contextName());
            operation.setVersionNo(route.getVersionNo());
            operation.setSequenceNo(dto.getSequenceNo());
            operation.setProcessParamJson(buildOperationParamJson(dto, operationCode, master, operationCraftCode,
                materialStatusCode, businessOperationCode, generatedFinishedProductCode, codeContext));
            operation.setStandardTimeMins(dto.getStandardTimeMins() != null
                ? dto.getStandardTimeMins()
                : master == null ? null : master.getStandardTimeMins());
            operation.setQualityRequirement(StringUtils.hasText(dto.getQualityRequirement())
                ? dto.getQualityRequirement()
                : master == null ? dto.getQualityRequirement() : master.getQualityRequirement());
            operation.setStatus(STATUS_CONFIRMED.equals(route.getStatus()) ? STATUS_CONFIRMED : STATUS_DRAFT);
            operation.setRemark(dto.getRemark());
            fillCreateAudit(operation, now, operator);
            processRepository.insert(operation);
        }
    }

    private ProcessEntity resolveOperationMaster(Long operationMasterProcessId) {
        if (operationMasterProcessId == null) {
            return null;
        }
        ProcessEntity master = processRepository.selectById(operationMasterProcessId);
        if (master == null || Integer.valueOf(1).equals(master.getDeletedFlag())) {
            throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "operation master not found");
        }
        if (!TYPE_OPERATION_MASTER.equals(master.getProcessType())) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "selected process is not operation master");
        }
        if (!List.of("confirmed", "locked").contains(master.getStatus())) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "operation master is not available");
        }
        return master;
    }

    private String resolveOperationCode(ProcessOperationDTO dto, ProcessEntity master) {
        if (StringUtils.hasText(dto.getOperationCode())) {
            return normalizeCode(dto.getOperationCode());
        }
        if (master != null && StringUtils.hasText(master.getProcessCode())) {
            return normalizeCode(master.getProcessCode());
        }
        return "OP-" + dto.getSequenceNo();
    }

    private String resolveOperationName(ProcessOperationDTO dto, ProcessEntity master) {
        if (StringUtils.hasText(dto.getProcessName())) {
            return dto.getProcessName().trim();
        }
        if (master != null && StringUtils.hasText(master.getProcessName())) {
            return master.getProcessName().trim();
        }
        throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "工序名称不能为空");
    }

    private String buildRouteOperationProcessCode(ProcessEntity route, ProcessOperationDTO dto, String operationCode) {
        String generated = route.getProcessCode()
            + "-OP-"
            + String.format("%03d", dto.getSequenceNo())
            + "-"
            + sanitizeCode(operationCode);
        return compactGeneratedCode(generated, PROCESS_CODE_MAX_LENGTH);
    }

    private String compactGeneratedCode(String value, int maxLength) {
        if (value.length() <= maxLength) {
            return value;
        }
        String hash = String.format("%08X", value.hashCode());
        return value.substring(0, maxLength - hash.length() - 1) + "-" + hash;
    }

    @SuppressWarnings("unchecked")
    private String buildOperationParamJson(ProcessOperationDTO dto, String operationCode, ProcessEntity master,
                                           String operationCraftCode, String materialStatusCode,
                                           String businessOperationCode, String generatedFinishedProductCode,
                                           CodeGenerationContext codeContext) {
        Map<String, Object> params = new LinkedHashMap<>();
        if (master != null && StringUtils.hasText(master.getProcessParamJson())) {
            try {
                JsonNode metadata = objectMapper.readTree(master.getProcessParamJson());
                JsonNode defaultParams = metadata.get("defaultProcessParamJson");
                if (defaultParams != null && defaultParams.isObject()) {
                    params.putAll(objectMapper.convertValue(defaultParams, Map.class));
                }
            } catch (Exception ignored) {
                // Historical master metadata can be non-standard; project route save remains resilient.
            }
        }
        if (StringUtils.hasText(dto.getProcessParamJson())) {
            try {
                params.putAll(objectMapper.readValue(dto.getProcessParamJson(), Map.class));
            } catch (Exception ex) {
                throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "processParamJson must be a JSON object");
            }
        }
        params.put("operationCode", operationCode);
        params.put("operationSource", StringUtils.hasText(dto.getOperationSource())
            ? dto.getOperationSource()
            : master == null ? "manual_snapshot" : "master");
        params.put("operationCraftCode", operationCraftCode);
        params.put("materialStatusCode", materialStatusCode);
        params.put("finishedProductFlag", Boolean.TRUE.equals(dto.getFinishedProductFlag()));
        params.put("businessOperationCode", businessOperationCode);
        params.put("businessOperationCodeManualFlag", Boolean.TRUE.equals(dto.getBusinessOperationCodeManualFlag())
            && StringUtils.hasText(businessOperationCode));
        params.put("productSpecificCode", codeContext.productSpecificCode());
        params.put("phoneModelCode", codeContext.phoneModelCode());
        params.put("colorCode", codeContext.colorCode());
        params.put("generatedFinishedProductCode", generatedFinishedProductCode);
        params.put("codeGenerationContext", codeContext.contextName());
        if (master != null) {
            params.put("operationMasterProcessId", master.getProcessId());
            params.put("operationMasterCode", master.getProcessCode());
            params.put("operationMasterName", master.getProcessName());
        }
        try {
            return objectMapper.writeValueAsString(params);
        } catch (Exception ex) {
            throw new BusinessException(ErrorCodeConstants.INTERNAL_ERROR, "failed to build operation params");
        }
    }

    private String resolveBusinessOperationCode(ProcessOperationDTO dto, String operationCraftCode,
                                                CodeGenerationContext codeContext) {
        String baseCode = Boolean.TRUE.equals(dto.getBusinessOperationCodeManualFlag())
            && StringUtils.hasText(dto.getBusinessOperationCode())
            ? normalizeBusinessOperationCode(dto.getBusinessOperationCode())
            : buildProductLineBusinessOperationCode(codeContext.productSpecificCode(), operationCraftCode);
        if (!StringUtils.hasText(baseCode)) {
            return null;
        }
        if ("product_line_route".equals(codeContext.contextName())) {
            validateProductLineBusinessOperationCode(baseCode, codeContext.productSpecificCode(), operationCraftCode);
            return baseCode;
        }
        String modelCode = appendSuffixIfMissing(baseCode, codeContext.phoneModelCode());
        if ("model_variant_route".equals(codeContext.contextName())) {
            validateModelVariantBusinessOperationCode(modelCode, codeContext.phoneModelCode());
            return modelCode;
        }
        String skuCode = appendSuffixIfMissing(modelCode, codeContext.colorCode());
        validateSkuBusinessOperationCode(skuCode, codeContext.phoneModelCode(), codeContext.colorCode());
        return skuCode;
    }

    private CodeGenerationContext resolveCodeGenerationContext(Product product, ProcessOperationDTO dto, String operationCraftCode) {
        String contextName = resolveCodeGenerationContextName(product);
        String productSpecificCode = firstText(
            dto.getProductSpecificCode(),
            product.getProductSpecificCode()
        );
        productSpecificCode = normalizeCompactCode(productSpecificCode);
        String phoneModelCode = firstText(
            dto.getPhoneModelCode(),
            product.getPhoneModelCode()
        );
        String colorCode = firstText(dto.getColorCode(), product.getColorCode());
        if ("product_line_route".equals(contextName)) {
            phoneModelCode = null;
            colorCode = null;
        } else if ("model_variant_route".equals(contextName)) {
            phoneModelCode = normalizeCodeOrNull(phoneModelCode);
            colorCode = null;
            validatePhoneModelCode(phoneModelCode);
        } else {
            phoneModelCode = normalizeCodeOrNull(phoneModelCode);
            colorCode = normalizeCodeOrNull(colorCode);
            validateConcreteCodeContext(phoneModelCode, colorCode);
        }
        return new CodeGenerationContext(
            productSpecificCode,
            normalizeCode(operationCraftCode),
            phoneModelCode,
            colorCode,
            contextName
        );
    }

    private void validateCodeGenerationContext(Product product, List<ProcessOperationDTO> operations) {
        String contextName = resolveCodeGenerationContextName(product);
        if ("product_line_route".equals(contextName)) {
            return;
        }
        for (ProcessOperationDTO operation : operations) {
            String phoneModelCode = normalizeCodeOrNull(firstText(
                operation.getPhoneModelCode(),
                product.getPhoneModelCode()
            ));
            String colorCode = normalizeCodeOrNull(firstText(
                operation.getColorCode(),
                product.getColorCode()
            ));
            if ("model_variant_route".equals(contextName)) {
                validatePhoneModelCode(phoneModelCode);
            } else {
                validateConcreteCodeContext(phoneModelCode, colorCode);
            }
        }
    }

    private void validatePhoneModelCode(String phoneModelCode) {
        if (!StringUtils.hasText(phoneModelCode) || !phoneModelCode.matches("[A-Z0-9]{4}")) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR,
                "具体型号或 SKU 必须提供 4 位手机型号编码");
        }
    }

    private void validateConcreteCodeContext(String phoneModelCode, String colorCode) {
        if (!StringUtils.hasText(phoneModelCode) || !phoneModelCode.matches("[A-Z0-9]{4}")) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR,
                "具体型号或 SKU 必须提供 4 位手机型号编码");
        }
        if (!StringUtils.hasText(colorCode) || !colorCode.matches("[A-Z0-9]{2}")) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR,
                "具体颜色或 SKU 必须提供 2 位颜色编码");
        }
    }

    private String resolveCodeGenerationContextName(Product product) {
        String productType = normalizeCode(product.getProductType());
        return switch (productType == null ? "" : productType) {
            case "SKU" -> "sku_route";
            case "MODEL_VARIANT" -> "model_variant_route";
            default -> "product_line_route";
        };
    }

    private String resolveGeneratedFinishedProductCode(String operationCraftCode, String businessOperationCode) {
        if (!StringUtils.hasText(operationCraftCode) || !StringUtils.hasText(businessOperationCode)) {
            return null;
        }
        return ProductBusinessCodeGenerator.DEFAULT_FINAL_OPERATION_CODE.equals(normalizeCode(operationCraftCode))
            ? businessOperationCode
            : null;
    }

    private String buildProductLineBusinessOperationCode(String productSpecificCode, String operationCraftCode) {
        String product = normalizeCompactCode(productSpecificCode);
        String operation = normalizeOperationCraftCode(operationCraftCode);
        if (!StringUtils.hasText(product) || !StringUtils.hasText(operation)) {
            return null;
        }
        return ProductBusinessCodeGenerator.PRODUCT_STATE_PREFIX + product + operation;
    }

    private String appendSuffixIfMissing(String value, String suffix) {
        String normalizedValue = normalizeBusinessOperationCode(value);
        String normalizedSuffix = normalizeCompactCode(suffix);
        if (!StringUtils.hasText(normalizedValue) || !StringUtils.hasText(normalizedSuffix)) {
            return normalizedValue;
        }
        return normalizedValue.endsWith(normalizedSuffix) ? normalizedValue : normalizedValue + normalizedSuffix;
    }

    private void validateProductLineBusinessOperationCode(String code, String productSpecificCode, String operationCraftCode) {
        validateBusinessOperationCode(code);
        String product = normalizeCompactCode(productSpecificCode);
        String operation = normalizeOperationCraftCode(operationCraftCode);
        if (!StringUtils.hasText(product) || !StringUtils.hasText(operation)) {
            return;
        }
        if (!normalizeBusinessOperationCode(code).endsWith(product + operation)) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR,
                "product line businessOperationCode must include productSpecificCode and operationCraftCode");
        }
    }

    private void validateModelVariantBusinessOperationCode(String code, String phoneModelCode) {
        validateBusinessOperationCode(code);
        String suffix = normalizeCompactCode(phoneModelCode);
        if (StringUtils.hasText(suffix) && !normalizeBusinessOperationCode(code).endsWith(suffix)) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR,
                "model variant businessOperationCode must end with phoneModelCode");
        }
    }

    private void validateSkuBusinessOperationCode(String code, String phoneModelCode, String colorCode) {
        validateBusinessOperationCode(code);
        String phone = normalizeCompactCode(phoneModelCode);
        String color = normalizeCompactCode(colorCode);
        if (!StringUtils.hasText(phone) || !StringUtils.hasText(color)) {
            return;
        }
        if (!normalizeBusinessOperationCode(code).endsWith(phone + color)) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR,
                "sku businessOperationCode must end with phoneModelCode and colorCode");
        }
    }

    private String normalizeCompactCode(String value) {
        String normalized = normalizeCode(value);
        return StringUtils.hasText(normalized) ? normalized.replace("-", "") : null;
    }

    private String normalizeCodeOrNull(String value) {
        return normalizeCompactCode(value);
    }

    private String firstText(String... values) {
        for (String value : values) {
            if (StringUtils.hasText(value)) {
                return value;
            }
        }
        return null;
    }

    private String resolveOperationCraftCode(ProcessOperationDTO dto, ProcessEntity master) {
        String dtoValue = normalizeOperationCraftCode(dto.getOperationCraftCode());
        if (StringUtils.hasText(dtoValue)) {
            return dtoValue;
        }
        String masterValue = master == null ? null : textFromJson(master.getProcessParamJson(), "operationCraftCode");
        if (StringUtils.hasText(masterValue)) {
            return normalizeOperationCraftCode(masterValue);
        }
        if (master != null && StringUtils.hasText(master.getProcessCode())) {
            return DEFAULT_OPERATION_CRAFT_CODES.get(master.getProcessCode().trim().toUpperCase());
        }
        return null;
    }

    private void validateOperationCraftCode(String operationCraftCode) {
        if (!StringUtils.hasText(operationCraftCode)) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "工序编码不能为空");
        }
        if (!operationCraftCode.matches("[A-Z0-9_-]{1,20}")) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "工序编码格式不正确");
        }
    }

    private String normalizeOperationCraftCode(String value) {
        String normalized = normalizeCode(value);
        if (!StringUtils.hasText(normalized)) {
            return null;
        }
        return switch (normalized) {
            case "10" -> "1010";
            case "20", "30", "51", "52" -> "1020";
            case "40" -> ProductBusinessCodeGenerator.DEFAULT_FINAL_OPERATION_CODE;
            default -> normalized;
        };
    }

    private void validateMaterialStatusCode(String materialStatusCode) {
        String normalized = normalizeCode(materialStatusCode);
        if (!StringUtils.hasText(normalized)) {
            return;
        }
        if (FORBIDDEN_MATERIAL_STATUS_CODES.contains(normalized)) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "finished product must use finishedProductFlag, not materialStatusCode");
        }
        if (!normalized.matches("[A-Z0-9_-]{1,20}")) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "materialStatusCode format is invalid");
        }
    }

    private void validateBusinessOperationCode(String businessOperationCode) {
        if (!StringUtils.hasText(businessOperationCode)) {
            return;
        }
        if (!normalizeBusinessOperationCode(businessOperationCode).matches("[A-Z0-9_-]{2,80}")) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "businessOperationCode format is invalid");
        }
    }

    private void ensureBusinessOperationCodeAvailable(Long parentProcessId, String businessOperationCode) {
        LambdaQueryWrapper<ProcessEntity> wrapper = new LambdaQueryWrapper<ProcessEntity>()
            .eq(ProcessEntity::getParentProcessId, parentProcessId)
            .eq(ProcessEntity::getBusinessOperationCode, businessOperationCode)
            .eq(ProcessEntity::getProcessType, TYPE_OPERATION)
            .eq(ProcessEntity::getDeletedFlag, 0);
        Long count = processRepository.selectCount(wrapper);
        if (count != null && count > 0) {
            throw new BusinessException(ErrorCodeConstants.CODE_CONFLICT, "businessOperationCode already exists: " + businessOperationCode);
        }
    }

    private String textFromJson(String json, String fieldName) {
        if (!StringUtils.hasText(json)) {
            return null;
        }
        try {
            JsonNode node = objectMapper.readTree(json);
            JsonNode value = node.get(fieldName);
            return value == null || value.isNull() ? null : value.asText();
        } catch (Exception ignored) {
            return null;
        }
    }

    private String normalizeCode(String value) {
        return StringUtils.hasText(value) ? value.trim().toUpperCase() : null;
    }

    private String normalizeBusinessOperationCode(String value) {
        return normalizeCode(value);
    }

    private String sanitizeCode(String value) {
        if (!StringUtils.hasText(value)) {
            return "NA";
        }
        return value.trim().replaceAll("[^A-Za-z0-9_-]", "-").replaceAll("-{2,}", "-").toUpperCase();
    }

    private record CodeGenerationContext(String productSpecificCode, String operationCraftCode, String phoneModelCode,
                                         String colorCode, String contextName) {
        private boolean ready() {
            return StringUtils.hasText(productSpecificCode)
                && StringUtils.hasText(operationCraftCode)
                && StringUtils.hasText(phoneModelCode)
                && StringUtils.hasText(colorCode);
        }
    }

    private void softDeleteOperations(Long processId) {
        processRepository.update(null, new UpdateWrapper<ProcessEntity>()
            .set("deleted_flag", 1)
            .set("updated_at", LocalDateTime.now())
            .set("updated_by", currentUserName())
            .eq("parent_process_id", processId)
            .eq("process_type", TYPE_OPERATION)
            .eq("deleted_flag", 0));
    }

    private void fillCreateAudit(com.yuewei.plm.repository.entity.BaseEntity entity, LocalDateTime now, String operator) {
        entity.setCreatedAt(now);
        entity.setCreatedBy(operator);
        entity.setUpdatedAt(now);
        entity.setUpdatedBy(operator);
        entity.setDeletedFlag(0);
    }

    private void fillUpdateAudit(com.yuewei.plm.repository.entity.BaseEntity entity) {
        entity.setUpdatedAt(LocalDateTime.now());
        entity.setUpdatedBy(currentUserName());
    }

    private String currentUserName() {
        return CurrentUserContext.get()
            .map(CurrentUser::displayName)
            .filter(StringUtils::hasText)
            .orElse("system");
    }

    private void writeLog(String action, ProcessEntity route, Product product, String detailJson, HttpServletRequest request) {
        operationLogService.logSuccess(OperationLogCreateCommand.builder()
            .action(action)
            .businessType("PROCESS")
            .businessId(String.valueOf(route.getProcessId()))
            .businessCode(route.getProcessCode())
            .businessName(route.getProcessName())
            .detailJson(detailJson)
            .request(request)
            .build());
    }
}
