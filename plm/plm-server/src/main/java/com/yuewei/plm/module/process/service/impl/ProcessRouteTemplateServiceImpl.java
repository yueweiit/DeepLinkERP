package com.yuewei.plm.module.process.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.module.process.entity.ProcessEntity;
import com.yuewei.plm.module.process.repository.ProcessRepository;
import com.yuewei.plm.module.process.service.ProcessRouteTemplateService;
import com.yuewei.plm.module.process.vo.ProcessRouteTemplateOperationVO;
import com.yuewei.plm.module.process.vo.ProcessRouteTemplateVO;
import java.util.Comparator;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

@Service
@RequiredArgsConstructor
public class ProcessRouteTemplateServiceImpl implements ProcessRouteTemplateService {

    private static final String TYPE_ROUTE_TEMPLATE = "route_template";
    private static final String TYPE_ROUTE_TEMPLATE_OPERATION = "route_template_operation";
    private static final String COMMON_PRODUCT_CODE = "COMMON";

    private final ProcessRepository processRepository;
    private final ObjectMapper objectMapper;

    @Override
    public List<ProcessRouteTemplateVO> listTemplates(String productCode, Boolean onlyDefault) {
        return processRepository.selectList(new LambdaQueryWrapper<ProcessEntity>()
                .eq(ProcessEntity::getProcessType, TYPE_ROUTE_TEMPLATE)
                .eq(ProcessEntity::getDeletedFlag, 0)
                .ne(ProcessEntity::getStatus, "archived")
                .orderByAsc(ProcessEntity::getProcessCode))
            .stream()
            .map(this::toTemplateVO)
            .filter(template -> !Boolean.TRUE.equals(onlyDefault) || Boolean.TRUE.equals(template.getDefaultTemplate()))
            .filter(template -> !StringUtils.hasText(productCode)
                || !StringUtils.hasText(template.getProductCode())
                || COMMON_PRODUCT_CODE.equalsIgnoreCase(template.getProductCode())
                || productCode.equalsIgnoreCase(template.getProductCode()))
            .sorted(Comparator.comparing(ProcessRouteTemplateVO::getPriority, Comparator.nullsLast(Comparator.reverseOrder())))
            .toList();
    }

    @Override
    public ProcessRouteTemplateVO getPublishedTemplate(String routeTemplateCode, String versionNo) {
        if (!StringUtils.hasText(routeTemplateCode)) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "routeTemplateCode is required");
        }
        return listTemplates(null, false).stream()
            .filter(template -> routeTemplateCode.equals(template.getRouteTemplateCode()))
            .filter(template -> !StringUtils.hasText(versionNo) || versionNo.equals(template.getVersionNo()))
            .filter(template -> List.of("confirmed", "locked", "published").contains(template.getStatus()))
            .findFirst()
            .orElseThrow(() -> new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "process route template not found"));
    }

    private ProcessRouteTemplateVO toTemplateVO(ProcessEntity template) {
        JsonNode metadata = readMetadata(template.getProcessParamJson());
        return ProcessRouteTemplateVO.builder()
            .routeTemplateCode(template.getProcessCode())
            .routeTemplateName(template.getProcessName())
            .productCode(text(metadata, "productCode"))
            .versionNo(template.getVersionNo())
            .status(template.getStatus())
            .defaultTemplate(booleanValue(metadata, "defaultTemplate"))
            .priority(intValue(metadata, "priority"))
            .operations(listTemplateOperations(template.getProcessId()))
            .build();
    }

    private List<ProcessRouteTemplateOperationVO> listTemplateOperations(Long templateProcessId) {
        return processRepository.selectList(new LambdaQueryWrapper<ProcessEntity>()
                .eq(ProcessEntity::getParentProcessId, templateProcessId)
                .eq(ProcessEntity::getProcessType, TYPE_ROUTE_TEMPLATE_OPERATION)
                .eq(ProcessEntity::getDeletedFlag, 0)
                .orderByAsc(ProcessEntity::getSequenceNo))
            .stream()
            .map(this::toTemplateOperationVO)
            .toList();
    }

    private ProcessRouteTemplateOperationVO toTemplateOperationVO(ProcessEntity operation) {
        JsonNode metadata = readMetadata(operation.getProcessParamJson());
        return ProcessRouteTemplateOperationVO.builder()
            .operationCode(text(metadata, "operationCode", operation.getProcessCode()))
            .operationMasterProcessId(operation.getOperationMasterProcessId())
            .operationCraftCode(text(metadata, "operationCraftCode", operation.getOperationCraftCode()))
            .materialStatusCode(text(metadata, "materialStatusCode", operation.getMaterialStatusCode()))
            .finishedProductFlag(booleanValue(metadata, "finishedProductFlag"))
            .businessOperationCode(text(metadata, "businessOperationCode", operation.getBusinessOperationCode()))
            .businessOperationCodeManualFlag(booleanValue(metadata, "businessOperationCodeManualFlag"))
            .sequenceNo(operation.getSequenceNo())
            .processName(operation.getProcessName())
            .processParamJson(jsonText(metadata, "defaultProcessParamJson", operation.getProcessParamJson()))
            .standardTimeMins(operation.getStandardTimeMins())
            .qualityRequirement(operation.getQualityRequirement())
            .remark(operation.getRemark())
            .build();
    }

    private JsonNode readMetadata(String processParamJson) {
        if (!StringUtils.hasText(processParamJson)) {
            return objectMapper.createObjectNode();
        }
        try {
            return objectMapper.readTree(processParamJson);
        } catch (Exception ignored) {
            return objectMapper.createObjectNode();
        }
    }

    private String text(JsonNode node, String field) {
        return text(node, field, null);
    }

    private String text(JsonNode node, String field, String fallback) {
        JsonNode value = node.get(field);
        return value == null || value.isNull() ? fallback : value.asText();
    }

    private String jsonText(JsonNode node, String field, String fallback) {
        JsonNode value = node.get(field);
        return value == null || value.isNull() ? fallback : value.toString();
    }

    private Boolean booleanValue(JsonNode node, String field) {
        JsonNode value = node.get(field);
        return value != null && !value.isNull() && value.asBoolean(false);
    }

    private Integer intValue(JsonNode node, String field) {
        JsonNode value = node.get(field);
        return value == null || value.isNull() ? null : value.asInt();
    }
}
