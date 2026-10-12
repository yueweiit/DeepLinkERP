package com.yuewei.plm.module.integration.dingtalk.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.security.CurrentUserContext;
import com.yuewei.plm.common.util.ProductBusinessCodeGenerator;
import com.yuewei.plm.common.util.ProductCodeGenerator;
import com.yuewei.plm.module.bom.entity.ProductProductionColorDecision;
import com.yuewei.plm.module.bom.repository.ProductProductionColorDecisionRepository;
import com.yuewei.plm.module.bom.service.BomInheritanceService;
import com.yuewei.plm.module.integration.dingtalk.dto.DingTalkModelVariantReceiveDTO;
import com.yuewei.plm.module.integration.dingtalk.entity.IntegrationRecord;
import com.yuewei.plm.module.integration.dingtalk.repository.IntegrationRecordRepository;
import com.yuewei.plm.module.integration.dingtalk.vo.DingTalkModelVariantResultVO;
import com.yuewei.plm.module.integration.dingtalk.vo.MoldCodeMatchVO;
import com.yuewei.plm.module.operationlog.constant.OperationActionConstants;
import com.yuewei.plm.module.operationlog.service.OperationLogCreateCommand;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.order.entity.OrderEntity;
import com.yuewei.plm.module.order.service.OrderCreateCommand;
import com.yuewei.plm.module.order.service.OrderService;
import com.yuewei.plm.module.process.service.ProcessRouteInheritanceService;
import com.yuewei.plm.module.project.variant.dto.RequirementFormSaveDTO;
import com.yuewei.plm.module.project.variant.entity.ProductVariantColor;
import com.yuewei.plm.module.project.variant.entity.RequirementForm;
import com.yuewei.plm.module.project.variant.repository.ProductVariantColorRepository;
import com.yuewei.plm.module.project.variant.repository.RequirementFormRepository;
import com.yuewei.plm.module.project.variant.vo.RequirementFormVO;
import com.yuewei.plm.module.product.mold.service.ProductMoldCodeService;
import com.yuewei.plm.module.workflow.entity.WorkflowTemplate;
import com.yuewei.plm.module.workflow.service.WorkflowTemplateService;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.BaseEntity;
import com.yuewei.plm.repository.entity.Product;
import java.time.LocalDateTime;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

@Service
@RequiredArgsConstructor
public class DingTalkModelVariantService {
    private final ProductRepository productRepository;
    private final ProductProductionColorDecisionRepository colorDecisionRepository;
    private final IntegrationRecordRepository integrationRepository;
    private final RequirementFormRepository formRepository;
    private final ProductVariantColorRepository variantColorRepository;
    private final OrderService orderService;
    private final ProductCodeGenerator productCodeGenerator;
    private final ProductBusinessCodeGenerator businessCodeGenerator;
    private final MoldCodeIntakeService moldCodeIntakeService;
    private final DingTalkAttachmentArchiveService attachmentArchiveService;
    private final OperationLogService operationLogService;
    private final ObjectMapper objectMapper;
    private final WorkflowTemplateService workflowTemplateService;
    private final ProductMoldCodeService productMoldCodeService;
    private final ProcessRouteInheritanceService processRouteInheritanceService;
    private final BomInheritanceService bomInheritanceService;

    @Transactional
    public DingTalkModelVariantResultVO receive(DingTalkModelVariantReceiveDTO dto) {
        IntegrationRecord existing = first(integrationRepository.selectList(new LambdaQueryWrapper<IntegrationRecord>()
            .eq(IntegrationRecord::getSourceSystem, "dingtalk").eq(IntegrationRecord::getIntegrationType, "model_variant")
            .eq(IntegrationRecord::getExternalInstanceId, externalInstanceId(dto)).eq(IntegrationRecord::getDeletedFlag, 0)));
        if (existing != null) {
            ensureSameApprovalCallback(existing, dto);
            return result(existing, true);
        }
        if (!"approved".equals(dto.getApprovalStatus())) throw validation("钉钉审批未通过，不能创建项目");
        Product parent = resolveParentProduct(dto);
        if (!isUsableProductLine(parent)) throw validation("来源产品不存在或状态不允许作为新型号来源");
        List<ProductProductionColorDecision> decisions = safe(colorDecisionRepository.selectList(new LambdaQueryWrapper<ProductProductionColorDecision>()
            .eq(ProductProductionColorDecision::getProductId, parent.getProductId()).eq(ProductProductionColorDecision::getSelectedFlag, 1)
            .eq(ProductProductionColorDecision::getStatus, "confirmed").eq(ProductProductionColorDecision::getDeletedFlag, 0)));
        if (decisions.isEmpty()) throw validation("来源产品尚未确认批量生产颜色");
        LocalDateTime now = LocalDateTime.now();
        Product project = new Product();
        String projectName = projectName(dto);
        project.setParentProductId(parent.getProductId()); project.setProductCode(generateUniqueProductCode(projectName));
        project.setProductName(projectName); project.setProductType("model_variant"); project.setSeriesName(parent.getSeriesName());
        project.setModel(dto.getModel()); project.setVersionNo("A"); project.setStatus("developing"); project.setCurrentStepNo(1); project.setLockStatus("unlocked");
        project.setExpectedDeliveryDate(dto.getExpectedDeliveryDate());
        project.setSourceSystem("dingtalk");
        project.setSourceInstanceId(externalInstanceId(dto));
        project.setSourceFormUrl(dto.getReferenceUrl());
        project.setSourceApprovedAt(dto.getSourceApprovedAt());
        applyBusinessCodes(project, dto, parent, decisions);
        bindWorkflowTemplate(project);
        fill(project, dto.getCreatedBy(), now); productRepository.insert(project);
        List<MoldCodeMatchVO> moldMatches = moldCodeIntakeService.sync(dto, parent, project);
        refreshBusinessCodesAfterMoldSync(project, dto, parent, decisions, now);
        String attachmentStatus = attachmentArchiveService.archiveMetadata(dto.getAttachments(), project, null, "other", dto.getCreatedBy());
        RequirementForm form = new RequirementForm(); form.setProjectId(project.getProductId()); form.setDingTalkApprovalNo(dto.getDingTalkApprovalNo());
        form.setNetworkType(dto.getNetworkType()); form.setHoleType(dto.getHoleType()); form.setMobileFunction(dto.getMobileFunction()); form.setTipo(dto.getTipo());
        form.setPriority(dto.getPriority()); form.setManufacturingLocation(dto.getManufacturingLocation()); form.setMoldMarking(dto.getMoldMarking());
        form.setProductSpecificCode(dto.getProductSpecificCode()); form.setPhoneModelCode(dto.getPhoneModelCode());
        form.setMaterialCodes(dto.getMaterialCodes() == null ? null : String.join(",", dto.getMaterialCodes()));
        form.setMoldCodes(resolveStoredMoldCodes(dto, moldMatches)); form.setMoldMatchStatus(moldMatchStatus(moldMatches)); form.setMoldMatchJson(toJson(moldMatches));
        form.setReferenceUrl(dto.getReferenceUrl()); form.setRemark(dto.getRemark()); form.setExpectedDeliveryDate(dto.getExpectedDeliveryDate()); form.setStatus("draft");
        fill(form, dto.getCreatedBy(), now); formRepository.insert(form);
        for (ProductProductionColorDecision decision : decisions) variantColorRepository.insert(snapshot(project, parent, decision, dto.getCreatedBy(), now));
        inheritProcessRoutesAndBom(parent, project, decisions, dto.getCreatedBy());
        IntegrationRecord record = inboundRecord(dto, project, now);
        integrationRepository.insert(record);
        writeCreateLog(project, moldMatches, attachmentStatus);
        return result(record, false, attachmentStatus, moldMatches);
    }

    private Product resolveParentProduct(DingTalkModelVariantReceiveDTO dto) {
        List<String> moldCodes = businessCodeGenerator.splitCodes(dto.getMoldCodes());
        Product relationParent = productMoldCodeService.findByIncomingMoldCodes(moldCodes).orElse(null);
        Product explicitParent = dto.getParentProductId() == null ? null : productRepository.selectById(dto.getParentProductId());
        if (relationParent != null) {
            if (explicitParent != null && !Objects.equals(explicitParent.getProductId(), relationParent.getProductId())) {
                throw validation("来源产品ID与模具编码关联产品不一致");
            }
            dto.setParentProductId(relationParent.getProductId());
            return relationParent;
        }

        String productSpecificCode = resolveMoldProductSpecificCode(dto.getMoldCodes());
        Product parent = explicitParent;
        if (parent != null && StringUtils.hasText(productSpecificCode)
            && StringUtils.hasText(parent.getProductSpecificCode())
            && !Objects.equals(productSpecificCode, normalizeCode(parent.getProductSpecificCode()))) {
            throw validation("来源产品ID与模具编码产品特定编码不一致: " + productSpecificCode);
        }
        if (!isUsableProductLine(parent) && StringUtils.hasText(productSpecificCode)) {
            parent = findReleasedProductLineBySpecificCode(productSpecificCode);
        }
        if (parent == null) {
            if (StringUtils.hasText(productSpecificCode)) {
                throw validation("模具编码未匹配到系统已有来源产品: " + productSpecificCode);
            }
            throw validation("缺少来源产品ID，且模具编码无法提取产品特定编码");
        }
        dto.setParentProductId(parent.getProductId());
        return parent;
    }

    private Product findReleasedProductLineBySpecificCode(String productSpecificCode) {
        List<Product> matches = productRepository.selectList(new LambdaQueryWrapper<Product>()
            .eq(Product::getProductSpecificCode, productSpecificCode)
            .eq(Product::getProductType, "product_line")
            .eq(Product::getStatus, "released")
            .eq(Product::getDeletedFlag, 0));
        if (matches.size() > 1) {
            throw validation("模具编码产品特定编码匹配到多个已发布来源产品: " + productSpecificCode);
        }
        return first(matches);
    }

    private boolean isUsableProductLine(Product product) {
        return product != null && "product_line".equals(product.getProductType())
            && Set.of("released", "archived").contains(product.getStatus());
    }

    private String normalizeCode(String value) {
        return StringUtils.hasText(value) ? value.trim().toUpperCase() : null;
    }

    private String resolveMoldProductSpecificCode(String moldCodes) {
        List<String> codes = businessCodeGenerator.splitCodes(moldCodes);
        if (codes.isEmpty()) {
            return null;
        }
        List<String> productCodes = codes.stream()
            .map(code -> businessCodeGenerator.parseMoldCode(code, null, List.of(), null).productSpecificCode())
            .distinct()
            .toList();
        if (productCodes.size() > 1) {
            throw validation("多个模具编码的产品特定编码不一致: " + String.join(",", productCodes));
        }
        return productCodes.get(0);
    }

    public RequirementFormVO getRequirementForm(Long projectId) {
        Product product = requireProject(projectId); RequirementForm form = requireForm(projectId);
        return toVO(product, form, colors(projectId));
    }

    @Transactional public RequirementFormVO saveRequirementForm(Long projectId, RequirementFormSaveDTO dto) { return save(projectId, dto, false); }
    @Transactional public RequirementFormVO confirmRequirementForm(Long projectId, RequirementFormSaveDTO dto) { return save(projectId, dto, true); }

    private RequirementFormVO save(Long projectId, RequirementFormSaveDTO dto, boolean confirm) {
        Product product = requireProject(projectId); RequirementForm form = requireForm(projectId); List<ProductVariantColor> colors = colors(projectId);
        Set<Long> requested = new HashSet<>(dto.getSelectedVariantColorIds() == null ? List.of() : dto.getSelectedVariantColorIds());
        Set<Long> allowed = colors.stream().map(ProductVariantColor::getVariantColorId).collect(java.util.stream.Collectors.toSet());
        if (!allowed.containsAll(requested)) throw validation("提交了来源颜色池之外的颜色");
        if (confirm && requested.isEmpty()) throw validation("至少保留一个生产颜色");
        if (confirm && !List.of("customer_requirement", "market_requirement").contains(dto.getRequirementType())) throw validation("请选择订单类型");
        if (confirm && "customer_requirement".equals(dto.getRequirementType()) && !StringUtils.hasText(dto.getCustomerRequirement())) throw validation("请填写客户要求");
        LocalDateTime now = LocalDateTime.now(); String operator = currentOperator(dto);
        syncRequirementFormToProduct(product, dto, operator, now);
        form.setNetworkType(dto.getNetworkType()); form.setHoleType(dto.getHoleType()); form.setMobileFunction(dto.getMobileFunction()); form.setTipo(dto.getTipo());
        form.setPriority(dto.getPriority()); form.setManufacturingLocation(dto.getManufacturingLocation()); form.setMoldMarking(dto.getMoldMarking());
        form.setReferenceUrl(dto.getReferenceUrl()); form.setRemark(dto.getRemark()); form.setExpectedDeliveryDate(dto.getExpectedDeliveryDate());
        form.setRequirementType(dto.getRequirementType()); form.setCustomerRequirement(dto.getCustomerRequirement()); form.setStatus(confirm ? "confirmed" : "draft");
        if (confirm) { form.setConfirmedAt(now); form.setConfirmedBy(operator); }
        form.setUpdatedAt(now); form.setUpdatedBy(operator); formRepository.updateById(form);
        for (ProductVariantColor color : colors) { boolean selected = requested.contains(color.getVariantColorId()); color.setSelectedFlag(selected ? 1 : 0); color.setDeselectedAt(selected ? null : now); color.setDeselectedBy(selected ? null : operator); color.setUpdatedAt(now); color.setUpdatedBy(operator); variantColorRepository.updateById(color); }
        if (confirm) {
            OrderEntity order = orderService.findByProjectId(projectId);
            if (order == null) {
                order = orderService.create(OrderCreateCommand.builder().projectId(projectId).productId(projectId).customerId(product.getCustomerId())
                    .dingTalkApprovalNo(form.getDingTalkApprovalNo()).projectType(product.getProductType()).phoneModel(product.getModel()).productName(product.getProductName())
                    .orderType(dto.getRequirementType()).orderTitle(product.getProductName()).customerRequirement(dto.getCustomerRequirement()).priorityLevel(dto.getPriority())
                    .expectedDate(dto.getExpectedDeliveryDate()).operator(operator).build());
            }
            startModelVariantTimeline(product, operator, now);
            IntegrationRecord record = first(integrationRepository.selectList(new LambdaQueryWrapper<IntegrationRecord>().eq(IntegrationRecord::getProjectId, projectId).eq(IntegrationRecord::getDeletedFlag, 0)));
            if (record != null) { record.setOrderId(order.getOrderId()); record.setUpdatedAt(now); record.setUpdatedBy(operator); integrationRepository.updateById(record); }
            writeRequirementFormConfirmLog(product, form, order, operator);
        }
        return toVO(product, form, colors);
    }

    private void syncRequirementFormToProduct(Product product, RequirementFormSaveDTO dto, String operator, LocalDateTime now) {
        if (StringUtils.hasText(dto.getModel())) product.setModel(dto.getModel().trim());
        if (StringUtils.hasText(dto.getTipo()) && StringUtils.hasText(product.getModel())) product.setProductName(dto.getTipo().trim() + " " + product.getModel().trim());
        if (dto.getExpectedDeliveryDate() != null) product.setExpectedDeliveryDate(dto.getExpectedDeliveryDate());
        if (dto.getReferenceUrl() != null) product.setSourceFormUrl(dto.getReferenceUrl());
        if (dto.getRemark() != null) product.setRemark(dto.getRemark());
        product.setUpdatedAt(now); product.setUpdatedBy(operator); productRepository.updateById(product);
    }

    private ProductVariantColor snapshot(Product project, Product parent, ProductProductionColorDecision d, String operator, LocalDateTime now) {
        ProductVariantColor value = new ProductVariantColor(); value.setProjectProductId(project.getProductId()); value.setSourceProductId(parent.getProductId());
        value.setSourceDecisionId(d.getProductProductionColorDecisionId()); value.setCodeItemId(d.getCodeItemId()); value.setColorCode(d.getColorCode()); value.setColorName(d.getColorName());
        value.setSourceDecisionBatchNo(d.getDecisionBatchNo()); value.setSourceConfirmedAt(d.getConfirmedAt()); value.setDefaultSelectedFlag(1); value.setSelectedFlag(1); value.setSnapshotStatus("active"); fill(value, operator, now); return value;
    }
    private void inheritProcessRoutesAndBom(Product parent, Product project, List<ProductProductionColorDecision> decisions, String operator) {
        List<String> inheritedColorNames = decisions.stream()
            .map(ProductProductionColorDecision::getColorName)
            .filter(StringUtils::hasText)
            .map(String::trim)
            .distinct()
            .toList();
        if (inheritedColorNames.isEmpty()) {
            throw validation("来源产品已确认生产颜色缺少颜色名称");
        }
        Map<Long, Long> processIdMapping = processRouteInheritanceService.inheritLatestReleasedFormalBomRoutesByColors(
            parent.getProductId(),
            project,
            inheritedColorNames,
            StringUtils.hasText(operator) ? operator : "system"
        );
        bomInheritanceService.inheritLatestReleasedByColors(
            parent.getProductId(),
            project.getProductId(),
            inheritedColorNames,
            processIdMapping
        );
    }
    private void refreshBusinessCodesAfterMoldSync(Product project, DingTalkModelVariantReceiveDTO dto, Product parent,
                                                   List<ProductProductionColorDecision> decisions, LocalDateTime now) {
        String beforeProductSpecificCode = project.getProductSpecificCode();
        String beforePhoneModelCode = project.getPhoneModelCode();
        String beforeColorCode = project.getColorCode();
        String beforeFinishedProductCode = project.getFinishedProductCode();
        applyBusinessCodes(project, dto, parent, decisions);
        if (Objects.equals(beforeProductSpecificCode, project.getProductSpecificCode())
            && Objects.equals(beforePhoneModelCode, project.getPhoneModelCode())
            && Objects.equals(beforeColorCode, project.getColorCode())
            && Objects.equals(beforeFinishedProductCode, project.getFinishedProductCode())) {
            return;
        }
        project.setUpdatedAt(now);
        project.setUpdatedBy(StringUtils.hasText(dto.getCreatedBy()) ? dto.getCreatedBy() : "system");
        productRepository.updateById(project);
    }
    private void applyBusinessCodes(Product project, DingTalkModelVariantReceiveDTO dto, Product parent,
                                    List<ProductProductionColorDecision> decisions) {
        project.setProductSpecificCode(normalizeCompactCode(firstText(
            dto.getProductSpecificCode(),
            parent.getProductSpecificCode(),
            parent.getProductCodePrefix(),
            project.getProductCodePrefix()
        )));
        project.setPhoneModelCode(normalizeCompactCode(firstText(dto.getPhoneModelCode(), deriveFourDigitCode(dto.getModel()))));
        String inheritedSingleColorCode = decisions != null && decisions.size() == 1
            ? decisions.get(0).getColorCode()
            : null;
        project.setColorCode(normalizeCompactCode(inheritedSingleColorCode));
        project.setFinishedProductCode(resolveFinishedProductCode(project));
    }
    private String resolveFinishedProductCode(Product project) {
        if (!StringUtils.hasText(project.getProductSpecificCode())
            || !StringUtils.hasText(project.getPhoneModelCode())
            || !StringUtils.hasText(project.getColorCode())) {
            return null;
        }
        return businessCodeGenerator.generateProductStateCode(
            project.getProductSpecificCode(),
            ProductBusinessCodeGenerator.DEFAULT_FINAL_OPERATION_CODE,
            project.getPhoneModelCode(),
            project.getColorCode()
        );
    }
    private String generateUniqueProductCode(String productName) {
        for (int attempt = 0; attempt < 10000; attempt++) {
            String candidate = productCodeGenerator.generate(productName);
            Long count = productRepository.selectCount(new LambdaQueryWrapper<Product>().eq(Product::getProductCode, candidate));
            if (count == null || count == 0) return candidate;
        }
        throw validation("无法生成唯一产品编码");
    }
    private RequirementFormVO toVO(Product p, RequirementForm f, List<ProductVariantColor> colors) {
        return RequirementFormVO.builder().projectId(p.getProductId()).dingTalkApprovalNo(f.getDingTalkApprovalNo())
            .productName(p.getProductName()).model(p.getModel()).networkType(f.getNetworkType()).holeType(f.getHoleType())
            .mobileFunction(f.getMobileFunction()).tipo(f.getTipo()).priority(f.getPriority())
            .manufacturingLocation(f.getManufacturingLocation()).moldMarking(f.getMoldMarking())
            .productSpecificCode(p.getProductSpecificCode()).phoneModelCode(p.getPhoneModelCode())
            .materialCodes(f.getMaterialCodes()).moldCodes(f.getMoldCodes()).moldMatchStatus(f.getMoldMatchStatus())
            .moldMatches(fromJson(f.getMoldMatchJson()))
            .referenceUrl(f.getReferenceUrl()).remark(f.getRemark()).expectedDeliveryDate(f.getExpectedDeliveryDate())
            .requirementType(f.getRequirementType()).customerRequirement(f.getCustomerRequirement()).status(f.getStatus())
            .colors(colors.stream().map(c -> RequirementFormVO.ColorVO.builder().variantColorId(c.getVariantColorId())
                .colorCode(c.getColorCode()).colorName(c.getColorName()).sourceConfirmedAt(c.getSourceConfirmedAt())
                .selected(Integer.valueOf(1).equals(c.getSelectedFlag())).build()).toList()).build();
    }
    private String projectName(DingTalkModelVariantReceiveDTO dto) {
        return dto.getTipo().trim() + " " + dto.getModel().trim();
    }
    private IntegrationRecord inboundRecord(DingTalkModelVariantReceiveDTO dto, Product project, LocalDateTime now) {
        IntegrationRecord record = new IntegrationRecord();
        record.setSourceSystem("dingtalk");
        record.setIntegrationType("model_variant");
        record.setExternalInstanceId(externalInstanceId(dto));
        record.setExternalStatus(dto.getApprovalStatus());
        record.setProcessCode(dto.getProcessCode());
        record.setDirection("inbound");
        record.setExternalUrl(dto.getReferenceUrl());
        record.setSourcePayloadJson(dto.getSourcePayloadJson());
        record.setProcessingStatus("success");
        record.setProjectId(project.getProductId());
        fill(record, dto.getCreatedBy(), now);
        return record;
    }
    private void ensureSameApprovalCallback(IntegrationRecord existing, DingTalkModelVariantReceiveDTO dto) {
        Map<String, Object> previous = payload(existing.getSourcePayloadJson());
        if (previous.isEmpty()) return;
        if (differs(previousText(previous, "approvalNo", "dingTalkApprovalNo"), dto.getDingTalkApprovalNo())
            || differs(previousText(previous, "parentProductId", "parent_product_id", "来源产品ID", "父产品ID"), String.valueOf(dto.getParentProductId()))
            || differs(previousText(previous, "tipo", "Tipo 类型", "产品类型", "类型"), dto.getTipo())
            || differs(previousText(previous, "model", "modelos", "Modelos 型号", "型号"), dto.getModel())
            || differs(previousText(previous, "moldCodes", "generatedCode", "生成的编码", "模具编码"), dto.getMoldCodes())) {
            throw validation("钉钉审批实例ID重复但审批内容不一致，请检查 approvalInstanceId 是否被配置为固定值: " + externalInstanceId(dto));
        }
    }
    private Map<String, Object> payload(String json) {
        if (!StringUtils.hasText(json)) return Map.of();
        try { return objectMapper.readValue(json, new TypeReference<Map<String, Object>>() {}); } catch (Exception ignored) { return Map.of(); }
    }
    private String previousText(Map<String, Object> payload, String... keys) {
        String rootValue = text(payload, keys);
        if (StringUtils.hasText(rootValue)) return rootValue;
        Object form = payload.get("form");
        if (form instanceof Map<?, ?> formMap) {
            for (String key : keys) {
                Object value = formMap.get(key);
                if (value != null && StringUtils.hasText(String.valueOf(value))) return String.valueOf(value).trim();
            }
        }
        return null;
    }
    private String text(Map<String, Object> payload, String... keys) {
        for (String key : keys) {
            Object value = payload.get(key);
            if (value != null && StringUtils.hasText(String.valueOf(value))) return String.valueOf(value).trim();
        }
        return null;
    }
    private boolean differs(String previous, String current) {
        return StringUtils.hasText(previous) && StringUtils.hasText(current) && !previous.trim().equals(current.trim());
    }
    private String externalInstanceId(DingTalkModelVariantReceiveDTO dto) {
        return StringUtils.hasText(dto.getApprovalInstanceId()) ? dto.getApprovalInstanceId() : dto.getDingTalkApprovalNo();
    }

    private String currentOperator(RequirementFormSaveDTO dto) {
        return CurrentUserContext.get()
            .map(currentUser -> currentUser.displayName())
            .filter(StringUtils::hasText)
            .orElseGet(() -> StringUtils.hasText(dto.getOperator()) ? dto.getOperator() : "system");
    }

    private void startModelVariantTimeline(Product product, String operator, LocalDateTime now) {
        if (!"model_variant".equals(product.getProductType())) {
            throw validation("只有新型号项目可以使用新型号信息完善表");
        }
        boolean timelineAlreadyStarted = "developing".equals(product.getStatus())
            && product.getCurrentStepNo() != null
            && product.getCurrentStepNo() >= 1;
        if (timelineAlreadyStarted) {
            return;
        }
        product.setCurrentStepNo(1);
        product.setTimelineCurrentConfirmed(false);
        product.setTimelineConfirmedNodeKey(null);
        product.setStatus("developing");
        product.setUpdatedAt(now);
        product.setUpdatedBy(operator);
        productRepository.updateById(product);
    }

    private void writeRequirementFormConfirmLog(Product product, RequirementForm form, OrderEntity order, String operator) {
        operationLogService.logSuccess(OperationLogCreateCommand.builder()
            .action(OperationActionConstants.MODEL_VARIANT_REQUIREMENT_FORM_CONFIRM)
            .businessType("PRODUCT")
            .businessId(String.valueOf(product.getProductId()))
            .businessCode(product.getProductCode())
            .businessName(product.getProductName())
            .detailJson("{"
                + "\"projectId\":" + product.getProductId()
                + ",\"productId\":" + product.getProductId()
                + ",\"requirementFormStatus\":\"" + json(form.getStatus()) + "\""
                + ",\"orderId\":" + (order == null || order.getOrderId() == null ? "null" : order.getOrderId())
                + ",\"afterTimelineStarted\":true"
                + ",\"currentStepNo\":" + product.getCurrentStepNo()
                + ",\"currentNodeKey\":\"MODEL_VARIANT_INIT_CREATE\""
                + ",\"operator\":\"" + json(operator) + "\""
                + ",\"action\":\"confirm_and_start\""
                + "}")
            .build());
    }

    private void writeCreateLog(Product project, List<MoldCodeMatchVO> moldMatches, String attachmentStatus) {
        operationLogService.logSuccess(OperationLogCreateCommand.builder()
            .action(OperationActionConstants.DINGTALK_MODEL_VARIANT_CREATE)
            .businessType("PRODUCT")
            .businessId(String.valueOf(project.getProductId()))
            .businessCode(project.getProductCode())
            .businessName(project.getProductName())
            .detailJson("{\"action\":\"dingtalk_model_variant_create\",\"moldMatchCount\":" + (moldMatches == null ? 0 : moldMatches.size())
                + ",\"attachmentArchiveStatus\":\"" + json(attachmentStatus) + "\"}")
            .build());
    }
    private void bindWorkflowTemplate(Product product) {
        WorkflowTemplate template = workflowTemplateService.findActiveTemplate(product.getProductType());
        if (template == null) return;
        product.setWorkflowTemplateId(template.getWorkflowTemplateId());
        product.setWorkflowTemplateVersionNo(template.getVersionNo());
    }
    private DingTalkModelVariantResultVO result(IntegrationRecord r, boolean hit) { return result(r, hit, "already_recorded", List.of()); }
    private DingTalkModelVariantResultVO result(IntegrationRecord r, boolean hit, String attachmentStatus, List<MoldCodeMatchVO> moldMatches) {
        return DingTalkModelVariantResultVO.builder().integrationRecordId(r.getIntegrationRecordId()).projectId(r.getProjectId())
            .dingTalkApprovalNo(r.getExternalInstanceId()).status(r.getProcessingStatus()).idempotentHit(hit)
            .attachmentArchiveStatus(attachmentStatus).moldMatches(moldMatches).build();
    }
    private Product requireProject(Long id) { Product p = productRepository.selectById(id); if (p == null || Integer.valueOf(1).equals(p.getDeletedFlag())) throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "项目不存在"); return p; }
    private RequirementForm requireForm(Long id) { RequirementForm f = first(formRepository.selectList(new LambdaQueryWrapper<RequirementForm>().eq(RequirementForm::getProjectId, id).eq(RequirementForm::getDeletedFlag, 0))); if (f == null) throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "项目完善表不存在"); return f; }
    private List<ProductVariantColor> colors(Long id) { return safe(variantColorRepository.selectList(new LambdaQueryWrapper<ProductVariantColor>().eq(ProductVariantColor::getProjectProductId, id).eq(ProductVariantColor::getDeletedFlag, 0))); }
    private void fill(BaseEntity e, String user, LocalDateTime now) { e.setCreatedAt(now); e.setCreatedBy(user); e.setUpdatedAt(now); e.setUpdatedBy(user); e.setDeletedFlag(0); }
    private BusinessException validation(String message) { return new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, message); }
    private <T> T first(List<T> values) { return values == null || values.isEmpty() ? null : values.get(0); }
    private <T> List<T> safe(List<T> values) { return values == null ? List.of() : values; }
    private String normalizeCompactCode(String value) {
        String normalized = normalizeCode(value);
        return StringUtils.hasText(normalized) ? normalized.replace("-", "") : null;
    }
    private String deriveFourDigitCode(String value) {
        String normalized = normalizeCompactCode(value);
        if (!StringUtils.hasText(normalized)) {
            return null;
        }
        String digits = normalized.replaceAll("\\D", "");
        if (digits.length() >= 4) {
            return digits.substring(digits.length() - 4);
        }
        return null;
    }
    private String firstText(String... values) {
        for (String value : values) {
            if (StringUtils.hasText(value)) {
                return value;
            }
        }
        return null;
    }
    private String moldMatchStatus(List<MoldCodeMatchVO> matches) {
        if (matches == null || matches.isEmpty()) return "not_provided";
        return matches.stream().allMatch(match -> "linked_existing".equals(match.getMatchStatus())) ? "linked_existing" : "created_draft";
    }
    private String resolveStoredMoldCodes(DingTalkModelVariantReceiveDTO dto, List<MoldCodeMatchVO> matches) {
        if (StringUtils.hasText(dto.getMoldCodes())) return dto.getMoldCodes();
        if (matches == null || matches.isEmpty()) return null;
        return String.join(",", matches.stream().map(MoldCodeMatchVO::getMoldCode).toList());
    }
    private String toJson(List<MoldCodeMatchVO> matches) {
        if (matches == null || matches.isEmpty()) return null;
        try { return objectMapper.writeValueAsString(matches); } catch (Exception ex) { throw validation("模具编码匹配结果序列化失败"); }
    }
    private List<MoldCodeMatchVO> fromJson(String json) {
        if (!StringUtils.hasText(json)) return List.of();
        try { return objectMapper.readValue(json, new TypeReference<List<MoldCodeMatchVO>>() {}); } catch (Exception ignored) { return List.of(); }
    }
    private String json(String value) { return value == null ? "" : value.replace("\\", "\\\\").replace("\"", "\\\""); }
}
