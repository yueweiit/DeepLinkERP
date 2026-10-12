package com.yuewei.plm.module.integration.dingtalk.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.module.integration.dingtalk.config.DingTalkIntegrationProperties;
import com.yuewei.plm.module.integration.dingtalk.dto.DingTalkApprovalCallbackDTO;
import com.yuewei.plm.module.integration.dingtalk.dto.DingTalkModelVariantReceiveDTO;
import com.yuewei.plm.module.integration.dingtalk.dto.DingTalkProductLineReceiveDTO;
import java.time.DateTimeException;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

@Service
@RequiredArgsConstructor
public class DingTalkApprovalDispatchService {
    private final DingTalkIntegrationProperties properties;
    private final DingTalkProductLineService productLineService;
    private final DingTalkModelVariantService modelVariantService;
    private final ObjectMapper objectMapper;

    public Object dispatch(DingTalkApprovalCallbackDTO dto) {
        if (!properties.isEnabled()) {
            throw validation("钉钉集成未启用");
        }
        if (properties.getProductLineProcessCode().equals(dto.getProcessCode())) {
            return productLineService.receive(toProductLine(dto));
        }
        if (properties.getModelVariantProcessCode().equals(dto.getProcessCode())) {
            return modelVariantService.receive(toModelVariant(dto));
        }
        throw validation("未支持的钉钉审批流程: " + dto.getProcessCode());
    }

    private DingTalkProductLineReceiveDTO toProductLine(DingTalkApprovalCallbackDTO source) {
        source.setForm(effectiveForm(source));
        source.setApplicant(effectiveApplicant(source));
        DingTalkProductLineReceiveDTO dto = new DingTalkProductLineReceiveDTO();
        dto.setApprovalInstanceId(externalInstanceId(source));
        dto.setTaskId(text(source.getForm(), "taskId", "approvalTaskId", "审批任务ID"));
        dto.setApprovalTaskId(StringUtils.hasText(source.getApprovalTaskId()) ? source.getApprovalTaskId() : dto.getTaskId());
        dto.setApprovalNo(source.getApprovalNo());
        dto.setProcessCode(source.getProcessCode());
        dto.setApprovalStatus(source.getApprovalStatus());
        dto.setProductName(requiredText(source.getForm(), "productName", "产品名称", "新产品名称"));
        dto.setProductCodePrefix(text(source.getForm(), "productCodePrefix", "产品编码前缀", "编码前缀"));
        dto.setExpectedDeliveryDate(date(source.getForm(), "expectedDeliveryDate", "预计交付时间", "预计交付日期"));
        dto.setMoldCodePrefix(text(source.getForm(), "moldCodePrefix", "模具编码前缀"));
        dto.setProductionColors(text(source.getForm(), "productionColors", "productionColor", "color", "生产颜色"));
        dto.setMoldMaterials(text(source.getForm(), "moldMaterials", "moldMaterial", "material", "模具生产材质", "模具生产材料"));
        dto.setSourceApprovedAt(toLocalDateTime(source));
        dto.setFormUrl(source.getFormUrl());
        if (source.getApplicant() != null) {
            dto.setApplicantUserId(source.getApplicant().getUserId());
            dto.setApplicantUserName(source.getApplicant().getUserName());
            dto.setApplicantDepartmentName(source.getApplicant().getDepartmentName());
        }
        dto.setRemark(text(source.getForm(), "remark", "备注"));
        dto.setAttachments(source.getAttachments());
        dto.setSourcePayloadJson(sourcePayload(source));
        return dto;
    }

    private DingTalkModelVariantReceiveDTO toModelVariant(DingTalkApprovalCallbackDTO source) {
        source.setForm(effectiveForm(source));
        source.setApplicant(effectiveApplicant(source));
        DingTalkModelVariantReceiveDTO dto = new DingTalkModelVariantReceiveDTO();
        dto.setDingTalkApprovalNo(StringUtils.hasText(source.getApprovalNo()) ? source.getApprovalNo() : externalInstanceId(source));
        dto.setApprovalInstanceId(externalInstanceId(source));
        dto.setTaskId(text(source.getForm(), "taskId", "approvalTaskId", "审批任务ID"));
        dto.setApprovalTaskId(StringUtils.hasText(source.getApprovalTaskId()) ? source.getApprovalTaskId() : dto.getTaskId());
        dto.setProcessCode(source.getProcessCode());
        dto.setApprovalStatus(source.getApprovalStatus());
        dto.setParentProductId(optionalLong(source.getForm(), "parentProductId", "parent_product_id", "来源产品ID", "父产品ID"));
        dto.setModel(requiredText(source.getForm(), "model", "modelos", "Modelos 型号", "型号"));
        dto.setTipo(requiredText(source.getForm(), "tipo", "Tipo 类型", "产品类型", "类型"));
        dto.setMoldMarking(text(source.getForm(), "moldMarking", "Selle en el molde 模具印字", "模具印字"));
        dto.setProductSpecificCode(text(source.getForm(), "productSpecificCode", "产品特定编码"));
        dto.setPhoneModelCode(text(source.getForm(), "phoneModelCode", "手机型号编码"));
        dto.setMaterialCodes(list(source.getForm(), "materialCodes", "材质编码"));
        dto.setMoldCodes(text(source.getForm(), "moldCodes", "generatedCode", "生成的编码", "模具编码"));
        dto.setPriority(text(source.getForm(), "priority", "优先级"));
        dto.setManufacturingLocation(text(source.getForm(), "manufacturingLocation", "生产地点"));
        dto.setExpectedDeliveryDate(date(source.getForm(), "expectedDeliveryDate", "预计交付时间", "预计交付日期"));
        dto.setSourceApprovedAt(toLocalDateTime(source));
        dto.setReferenceUrl(source.getFormUrl());
        dto.setRemark(text(source.getForm(), "remark", "备注"));
        dto.setAttachments(source.getAttachments());
        dto.setSourcePayloadJson(sourcePayload(source));
        dto.setCreatedBy(source.getApplicant() != null && StringUtils.hasText(source.getApplicant().getUserName())
            ? source.getApplicant().getUserName()
            : "dingtalk");
        return dto;
    }

    private Map<String, Object> effectiveForm(DingTalkApprovalCallbackDTO source) {
        Map<String, Object> form = new LinkedHashMap<>();
        if (source.getForm() != null) {
            form.putAll(source.getForm());
        }
        putIfMissing(form, "parentProductId", source.getParentProductId());
        putIfMissing(form, "taskId", source.getTaskId());
        putIfMissing(form, "approvalTaskId", source.getApprovalTaskId());
        putIfMissing(form, "tipo", source.getTipo());
        putIfMissing(form, "model", source.getModel());
        putIfMissing(form, "moldMarking", source.getMoldMarking());
        putIfMissing(form, "moldCodes", source.getMoldCodes());
        putIfMissing(form, "generatedCode", source.getGeneratedCode());
        putIfMissing(form, "expectedDeliveryDate", source.getExpectedDeliveryDate());
        putIfMissing(form, "productName", source.getProductName());
        putIfMissing(form, "productCodePrefix", source.getProductCodePrefix());
        putIfMissing(form, "moldCodePrefix", source.getMoldCodePrefix());
        putIfMissing(form, "productionColors", source.getProductionColors());
        putIfMissing(form, "moldMaterials", source.getMoldMaterials());
        putIfMissing(form, "remark", source.getRemark());
        return form;
    }

    private DingTalkApprovalCallbackDTO.Applicant effectiveApplicant(DingTalkApprovalCallbackDTO source) {
        DingTalkApprovalCallbackDTO.Applicant applicant = source.getApplicant();
        if (applicant == null && (hasValue(source.getUserId()) || hasValue(source.getUserName()) || hasValue(source.getDepartmentName()))) {
            applicant = new DingTalkApprovalCallbackDTO.Applicant();
        }
        if (applicant != null) {
            if (!StringUtils.hasText(applicant.getUserId())) applicant.setUserId(source.getUserId());
            if (!StringUtils.hasText(applicant.getUserName())) applicant.setUserName(source.getUserName());
            if (!StringUtils.hasText(applicant.getDepartmentName())) applicant.setDepartmentName(source.getDepartmentName());
        }
        return applicant;
    }

    private void putIfMissing(Map<String, Object> form, String key, Object value) {
        if (!form.containsKey(key) && hasValue(value)) {
            form.put(key, value);
        }
    }

    private boolean hasValue(Object value) {
        return value != null && (!(value instanceof String text) || StringUtils.hasText(text));
    }

    private String text(Map<String, Object> form, String... keys) {
        if (form == null) return null;
        for (String key : keys) {
            Object value = form.get(key);
            if (value instanceof List<?> values) {
                String joined = values.stream()
                    .map(String::valueOf)
                    .map(String::trim)
                    .filter(StringUtils::hasText)
                    .collect(java.util.stream.Collectors.joining(","));
                if (StringUtils.hasText(joined)) return joined;
            }
            if (value != null && StringUtils.hasText(String.valueOf(value))) {
                return String.valueOf(value).trim();
            }
        }
        return null;
    }

    private String requiredText(Map<String, Object> form, String... keys) {
        String value = text(form, keys);
        if (!StringUtils.hasText(value)) {
            throw validation("钉钉审批表缺少字段: " + String.join("/", keys));
        }
        return value;
    }

    private Long requiredLong(Map<String, Object> form, String... keys) {
        String value = requiredText(form, keys);
        try {
            return Long.valueOf(value);
        } catch (NumberFormatException ex) {
            throw validation("钉钉审批表字段不是有效数字: " + String.join("/", keys));
        }
    }

    private Long optionalLong(Map<String, Object> form, String... keys) {
        String value = text(form, keys);
        if (!StringUtils.hasText(value)) {
            return null;
        }
        try {
            return Long.valueOf(value);
        } catch (NumberFormatException ex) {
            throw validation("钉钉审批表字段不是有效数字: " + String.join("/", keys));
        }
    }

    @SuppressWarnings("unchecked")
    private List<String> list(Map<String, Object> form, String... keys) {
        Object value = null;
        if (form != null) {
            for (String key : keys) {
                value = form.get(key);
                if (value != null) break;
            }
        }
        if (value instanceof List<?> values) {
            return values.stream().map(String::valueOf).filter(StringUtils::hasText).toList();
        }
        if (value != null && StringUtils.hasText(String.valueOf(value))) {
            return Arrays.stream(String.valueOf(value).split("[,;，；\\r\\n\\t ]+"))
                .filter(StringUtils::hasText)
                .toList();
        }
        return List.of();
    }

    private LocalDate date(Map<String, Object> form, String... keys) {
        String value = text(form, keys);
        if (!StringUtils.hasText(value)) {
            return null;
        }
        String normalized = value.trim().replace('/', '-').replace('.', '-');
        int timeSeparator = normalized.indexOf('T');
        if (timeSeparator > 0) {
            normalized = normalized.substring(0, timeSeparator);
        }
        int blankSeparator = normalized.indexOf(' ');
        if (blankSeparator > 0) {
            normalized = normalized.substring(0, blankSeparator);
        }
        String[] parts = normalized.split("-");
        if (parts.length != 3) {
            throw validation("钉钉审批表日期格式错误: " + String.join("/", keys));
        }
        try {
            return LocalDate.of(
                Integer.parseInt(parts[0]),
                Integer.parseInt(parts[1]),
                Integer.parseInt(parts[2])
            );
        } catch (NumberFormatException | DateTimeException ex) {
            throw validation("钉钉审批表日期格式错误: " + String.join("/", keys));
        }
    }

    private LocalDateTime toLocalDateTime(DingTalkApprovalCallbackDTO source) {
        return source.getApprovedAt() == null ? null : source.getApprovedAt().toLocalDateTime();
    }

    private String externalInstanceId(DingTalkApprovalCallbackDTO source) {
        if (StringUtils.hasText(source.getApprovalInstanceId())) return source.getApprovalInstanceId();
        if (StringUtils.hasText(source.getApprovalNo())) return source.getApprovalNo();
        throw validation("钉钉审批实例 ID 不能为空");
    }

    private String sourcePayload(DingTalkApprovalCallbackDTO source) {
        if (StringUtils.hasText(source.getSourcePayloadJson())) {
            return source.getSourcePayloadJson();
        }
        try {
            return objectMapper.writeValueAsString(source);
        } catch (Exception ignored) {
            return null;
        }
    }

    private BusinessException validation(String message) {
        return new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, message);
    }
}
