package com.yuewei.plm.module.process.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.common.security.CurrentUserContext;
import com.yuewei.plm.module.operationlog.constant.OperationActionConstants;
import com.yuewei.plm.module.operationlog.service.OperationLogCreateCommand;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.process.dto.ProcessOperationMasterSaveDTO;
import com.yuewei.plm.module.process.entity.ProcessEntity;
import com.yuewei.plm.module.process.repository.ProcessRepository;
import com.yuewei.plm.module.process.service.ProcessOperationMasterService;
import com.yuewei.plm.module.process.vo.ProcessOperationMasterVO;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

@Service
@RequiredArgsConstructor
public class ProcessOperationMasterServiceImpl implements ProcessOperationMasterService {

    public static final String TYPE_OPERATION_MASTER = "operation_master";
    private static final String STATUS_DRAFT = "draft";
    private static final String STATUS_CONFIRMED = "confirmed";
    private static final String STATUS_ARCHIVED = "archived";

    private final ProcessRepository processRepository;
    private final OperationLogService operationLogService;
    private final ObjectMapper objectMapper;

    @Override
    public List<ProcessOperationMasterVO> list(String keyword, String processCategory, String operationType, String status) {
        LambdaQueryWrapper<ProcessEntity> wrapper = new LambdaQueryWrapper<ProcessEntity>()
            .eq(ProcessEntity::getProcessType, TYPE_OPERATION_MASTER)
            .eq(ProcessEntity::getDeletedFlag, 0);
        if (StringUtils.hasText(keyword)) {
            wrapper.and(inner -> inner
                .like(ProcessEntity::getProcessCode, keyword)
                .or()
                .like(ProcessEntity::getProcessName, keyword));
        }
        if (StringUtils.hasText(status)) {
            wrapper.eq(ProcessEntity::getStatus, status);
        }
        wrapper.orderByAsc(ProcessEntity::getProcessCode);
        return processRepository.selectList(wrapper).stream()
            .map(ProcessOperationMasterVO::from)
            .filter(item -> !StringUtils.hasText(processCategory) || processCategory.equals(item.getProcessCategory()))
            .filter(item -> !StringUtils.hasText(operationType) || operationType.equals(item.getOperationType()))
            .toList();
    }

    @Override
    @Transactional
    public ProcessOperationMasterVO create(ProcessOperationMasterSaveDTO dto) {
        ensureProcessCodeAvailable(dto.getProcessCode(), null);
        ProcessEntity entity = new ProcessEntity();
        entity.setProductId(null);
        entity.setProcessCode(sanitizeCode(dto.getProcessCode()));
        entity.setProcessName(dto.getProcessName().trim());
        entity.setProcessType(TYPE_OPERATION_MASTER);
        entity.setVersionNo("V1");
        entity.setProcessParamJson(buildMetadataJson(dto));
        entity.setStandardTimeMins(dto.getDefaultStandardTimeMins());
        entity.setQualityRequirement(dto.getDefaultQualityRequirement());
        entity.setStatus(STATUS_DRAFT);
        entity.setRemark(dto.getRemark());
        fillCreateAudit(entity);
        processRepository.insert(entity);
        writeLog(OperationActionConstants.PROCESS_OPERATION_MASTER_CREATE, entity, "{\"action\":\"create\"}");
        return getById(entity.getProcessId());
    }

    @Override
    @Transactional
    public ProcessOperationMasterVO update(Long processId, ProcessOperationMasterSaveDTO dto) {
        ProcessEntity entity = getEntityOrThrow(processId);
        ensureProcessCodeAvailable(dto.getProcessCode(), processId);
        entity.setProcessCode(sanitizeCode(dto.getProcessCode()));
        entity.setProcessName(dto.getProcessName().trim());
        entity.setProcessParamJson(buildMetadataJson(dto));
        entity.setStandardTimeMins(dto.getDefaultStandardTimeMins());
        entity.setQualityRequirement(dto.getDefaultQualityRequirement());
        entity.setRemark(dto.getRemark());
        fillUpdateAudit(entity);
        processRepository.updateById(entity);
        writeLog(OperationActionConstants.PROCESS_OPERATION_MASTER_UPDATE, entity, "{\"action\":\"update\"}");
        return getById(processId);
    }

    @Override
    @Transactional
    public ProcessOperationMasterVO confirm(Long processId) {
        ProcessEntity entity = getEntityOrThrow(processId);
        entity.setStatus(STATUS_CONFIRMED);
        fillUpdateAudit(entity);
        processRepository.updateById(entity);
        writeLog(OperationActionConstants.PROCESS_OPERATION_MASTER_CONFIRM, entity, "{\"action\":\"confirm\"}");
        return ProcessOperationMasterVO.from(entity);
    }

    @Override
    @Transactional
    public ProcessOperationMasterVO archive(Long processId) {
        ProcessEntity entity = getEntityOrThrow(processId);
        entity.setStatus(STATUS_ARCHIVED);
        fillUpdateAudit(entity);
        processRepository.updateById(entity);
        writeLog(OperationActionConstants.PROCESS_OPERATION_MASTER_ARCHIVE, entity, "{\"action\":\"archive\"}");
        return ProcessOperationMasterVO.from(entity);
    }

    private ProcessOperationMasterVO getById(Long processId) {
        return ProcessOperationMasterVO.from(getEntityOrThrow(processId));
    }

    private ProcessEntity getEntityOrThrow(Long processId) {
        ProcessEntity entity = processRepository.selectById(processId);
        if (entity == null || Integer.valueOf(1).equals(entity.getDeletedFlag()) || !TYPE_OPERATION_MASTER.equals(entity.getProcessType())) {
            throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "operation master not found");
        }
        return entity;
    }

    private void ensureProcessCodeAvailable(String processCode, Long excludedProcessId) {
        LambdaQueryWrapper<ProcessEntity> wrapper = new LambdaQueryWrapper<ProcessEntity>()
            .eq(ProcessEntity::getProcessCode, sanitizeCode(processCode))
            .eq(ProcessEntity::getDeletedFlag, 0);
        if (excludedProcessId != null) {
            wrapper.ne(ProcessEntity::getProcessId, excludedProcessId);
        }
        Long count = processRepository.selectCount(wrapper);
        if (count != null && count > 0) {
            throw new BusinessException(ErrorCodeConstants.CODE_CONFLICT, "processCode already exists: " + processCode);
        }
    }

    private String buildMetadataJson(ProcessOperationMasterSaveDTO dto) {
        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("processCategory", dto.getProcessCategory());
        metadata.put("operationType", dto.getOperationType());
        metadata.put("operationCraftCode", normalizeCode(dto.getOperationCraftCode()));
        metadata.put("needWorkstation", Boolean.TRUE.equals(dto.getNeedWorkstation()));
        metadata.put("workstationType", dto.getWorkstationType());
        metadata.put("defaultProcessParamJson", parseJsonObject(dto.getDefaultProcessParamJson()));
        try {
            return objectMapper.writeValueAsString(metadata);
        } catch (Exception ex) {
            throw new BusinessException(ErrorCodeConstants.INTERNAL_ERROR, "failed to build operation master metadata");
        }
    }

    private JsonNode parseJsonObject(String json) {
        if (!StringUtils.hasText(json)) {
            return objectMapper.createObjectNode();
        }
        try {
            JsonNode node = objectMapper.readTree(json);
            if (!node.isObject()) {
                throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "defaultProcessParamJson must be a JSON object");
            }
            return node;
        } catch (BusinessException ex) {
            throw ex;
        } catch (Exception ex) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "defaultProcessParamJson must be a JSON object");
        }
    }

    private String sanitizeCode(String value) {
        if (!StringUtils.hasText(value)) {
            return "NA";
        }
        return value.trim().replaceAll("[^A-Za-z0-9_-]", "-").replaceAll("-{2,}", "-").toUpperCase();
    }

    private String normalizeCode(String value) {
        return StringUtils.hasText(value) ? value.trim().toUpperCase() : null;
    }

    private void fillCreateAudit(com.yuewei.plm.repository.entity.BaseEntity entity) {
        LocalDateTime now = LocalDateTime.now();
        String operator = currentUserName();
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

    private void writeLog(String action, ProcessEntity entity, String detailJson) {
        operationLogService.logSuccess(OperationLogCreateCommand.builder()
            .action(action)
            .businessType("PROCESS")
            .businessId(String.valueOf(entity.getProcessId()))
            .businessCode(entity.getProcessCode())
            .businessName(entity.getProcessName())
            .detailJson(detailJson)
            .build());
    }
}
