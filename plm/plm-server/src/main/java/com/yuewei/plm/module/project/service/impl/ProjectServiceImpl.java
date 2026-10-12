package com.yuewei.plm.module.project.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.constant.ProductStatusConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.vo.PageVO;
import com.yuewei.plm.module.bom.entity.ProductProductionColorDecision;
import com.yuewei.plm.module.bom.repository.ProductProductionColorDecisionRepository;
import com.yuewei.plm.module.code.entity.CodeItem;
import com.yuewei.plm.module.code.repository.CodeItemRepository;
import com.yuewei.plm.module.project.constant.TimelineNodeConstants;
import com.yuewei.plm.module.project.dto.ProjectQueryDTO;
import com.yuewei.plm.module.project.service.ProjectService;
import com.yuewei.plm.module.project.service.ProjectCostService;
import com.yuewei.plm.module.project.service.TimelineDefinitionProvider;
import com.yuewei.plm.module.project.service.TimelineService;
import com.yuewei.plm.module.project.vo.ProjectColorSummaryVO;
import com.yuewei.plm.module.project.variant.entity.RequirementForm;
import com.yuewei.plm.module.project.variant.repository.RequirementFormRepository;
import com.yuewei.plm.module.project.vo.ProjectDetailVO;
import com.yuewei.plm.module.project.vo.ProjectSummaryVO;
import com.yuewei.plm.module.user.entity.SysUser;
import com.yuewei.plm.module.user.repository.SysUserRepository;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.stream.Collectors;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

@Service
@RequiredArgsConstructor
public class ProjectServiceImpl implements ProjectService {

    private static final List<String> IN_PROGRESS_STATUSES = List.of(
        ProductStatusConstants.DRAFT,
        ProductStatusConstants.DEVELOPING
    );

    private final ProductRepository productRepository;
    private final SysUserRepository sysUserRepository;
    private final TimelineService timelineService;
    private final TimelineDefinitionProvider timelineDefinitionProvider;
    @Autowired(required = false)
    private RequirementFormRepository requirementFormRepository;
    @Autowired(required = false)
    private ProjectCostService projectCostService;
    @Autowired(required = false)
    private com.yuewei.plm.module.pilot.PilotAccessService pilotAccess;
    @Autowired(required = false)
    private ProductProductionColorDecisionRepository colorDecisionRepository;
    @Autowired(required = false)
    private CodeItemRepository codeItemRepository;

    @Override
    public PageVO<ProjectSummaryVO> pageInProgress(ProjectQueryDTO queryDTO) {
        LambdaQueryWrapper<Product> wrapper = baseQuery(queryDTO)
            .in(Product::getStatus, IN_PROGRESS_STATUSES)
            .orderByDesc(Product::getUpdatedAt);
        return pageProducts(queryDTO, wrapper);
    }

    @Override
    public PageVO<ProjectSummaryVO> page(ProjectQueryDTO queryDTO) {
        LambdaQueryWrapper<Product> wrapper = baseQuery(queryDTO)
            .eq(StringUtils.hasText(queryDTO.getStatus()), Product::getStatus, queryDTO.getStatus())
            .orderByDesc(Product::getUpdatedAt);
        return pageProducts(queryDTO, wrapper);
    }

    @Override
    public ProjectDetailVO getDetail(Long projectId) {
        Product product = getProductOrThrow(projectId);
        Map<Long, String> ownerNames = loadOwnerNames(List.of(product));
        Map<Long, String> moldCodes = loadMoldCodes(List.of(product));
        Integer currentStepNo = normalizeStepNo(product, product.getCurrentStepNo());
        var costSummary = projectCostService == null || (pilotAccess != null && !pilotAccess.hasPermission("finance:read"))
            ? null : projectCostService.getSummary(product.getProductId());
        return ProjectDetailVO.builder()
            .projectId(product.getProductId())
            .productId(product.getProductId())
            .parentProductId(product.getParentProductId())
            .customerId(product.getCustomerId())
            .productCode(product.getProductCode())
            .productSpecificCode(product.getProductSpecificCode())
            .phoneModelCode(product.getPhoneModelCode())
            .colorCode(product.getColorCode())
            .finishedProductCode(product.getFinishedProductCode())
            .importShortCode(product.getImportShortCode())
            .productName(product.getProductName())
            .productType(product.getProductType())
            .seriesName(product.getSeriesName())
            .model(product.getModel())
            .moldCodes(moldCodes.get(product.getProductId()))
            .color(product.getColor())
            .material(product.getMaterial())
            .packageType(product.getPackageType())
            .surfaceProcess(product.getSurfaceProcess())
            .coreProcess(product.getCoreProcess())
            .composition(product.getComposition())
            .ownerUserId(product.getOwnerUserId())
            .ownerUserName(ownerName(product, ownerNames))
            .versionNo(product.getVersionNo())
            .status(product.getStatus())
            .currentStepNo(currentStepNo)
            .currentNodeName(currentNodeName(product, currentStepNo))
            .moldTransferAt(product.getMoldTransferAt())
            .expectedArrivalAt(product.getExpectedArrivalAt())
            .actualArrivalAt(product.getActualArrivalAt())
            .documentCount(0)
            .totalCost(costSummary == null ? null : costSummary.getTotalCost())
            .currencyCode(costSummary == null ? "CNY" : costSummary.getCurrencyCode())
            .colorSummary(buildColorSummary(product))
            .timeline(timelineService.getTimeline(projectId))
            .remark(product.getRemark())
            .createdAt(product.getCreatedAt())
            .updatedAt(product.getUpdatedAt())
            .build();
    }

    @Override
    public ProjectSummaryVO getSummary(Long projectId) {
        Product product = getProductOrThrow(projectId);
        return toSummaryVO(product, loadOwnerNames(List.of(product)), loadMoldCodes(List.of(product)));
    }

    private PageVO<ProjectSummaryVO> pageProducts(ProjectQueryDTO queryDTO, LambdaQueryWrapper<Product> wrapper) {
        IPage<Product> page = productRepository.selectPage(new Page<>(queryDTO.getPage(), queryDTO.getSize()), wrapper);
        Map<Long, String> ownerNames = loadOwnerNames(page.getRecords());
        Map<Long, String> moldCodes = loadMoldCodes(page.getRecords());
        return PageVO.<ProjectSummaryVO>builder()
            .content(page.getRecords().stream().map(product -> toSummaryVO(product, ownerNames, moldCodes)).toList())
            .page(page.getCurrent())
            .size(page.getSize())
            .totalElements(page.getTotal())
            .totalPages(page.getPages())
            .build();
    }

    private LambdaQueryWrapper<Product> baseQuery(ProjectQueryDTO queryDTO) {
        return new LambdaQueryWrapper<Product>()
            .eq(StringUtils.hasText(queryDTO.getProductType()), Product::getProductType, queryDTO.getProductType())
            .eq(queryDTO.getOwnerUserId() != null, Product::getOwnerUserId, queryDTO.getOwnerUserId())
            .and(StringUtils.hasText(queryDTO.getKeyword()), wrapper -> wrapper
                .like(Product::getProductName, queryDTO.getKeyword())
                .or()
                .like(Product::getProductCode, queryDTO.getKeyword())
                .or()
                .like(Product::getModel, queryDTO.getKeyword()))
            .ne(Product::getDeletedFlag, 1);
    }

    private ProjectSummaryVO toSummaryVO(Product product, Map<Long, String> ownerNames, Map<Long, String> moldCodes) {
        Integer currentStepNo = normalizeStepNo(product, product.getCurrentStepNo());
        return ProjectSummaryVO.builder()
            .projectId(product.getProductId())
            .productId(product.getProductId())
            .parentProductId(product.getParentProductId())
            .productCode(product.getProductCode())
            .productSpecificCode(product.getProductSpecificCode())
            .phoneModelCode(product.getPhoneModelCode())
            .colorCode(product.getColorCode())
            .finishedProductCode(product.getFinishedProductCode())
            .importShortCode(product.getImportShortCode())
            .productName(product.getProductName())
            .productType(product.getProductType())
            .productTypeName(productTypeName(product.getProductType()))
            .model(product.getModel())
            .moldCodes(moldCodes.get(product.getProductId()))
            .color(product.getColor())
            .versionNo(product.getVersionNo())
            .status(product.getStatus())
            .statusName(statusName(product.getStatus()))
            .lockStatus(product.getLockStatus())
            .abandonedAt(product.getAbandonedAt())
            .abandonedBy(product.getAbandonedBy())
            .abandonReason(product.getAbandonReason())
            .ownerUserId(product.getOwnerUserId())
            .ownerUserName(ownerName(product, ownerNames))
            .currentStepNo(currentStepNo)
            .currentNodeName(currentNodeName(product, currentStepNo))
            .moldTransferAt(product.getMoldTransferAt())
            .expectedArrivalAt(product.getExpectedArrivalAt())
            .actualArrivalAt(product.getActualArrivalAt())
            .documentCount(0)
            .createdAt(product.getCreatedAt())
            .updatedAt(product.getUpdatedAt())
            .build();
    }

    private Map<Long, String> loadOwnerNames(Collection<Product> products) {
        Set<Long> ownerIds = products.stream()
            .map(Product::getOwnerUserId)
            .filter(Objects::nonNull)
            .collect(Collectors.toSet());
        if (ownerIds.isEmpty()) {
            return Map.of();
        }
        return sysUserRepository.selectBatchIds(ownerIds).stream()
            .collect(Collectors.toMap(SysUser::getUserId, SysUser::getDisplayName, (left, right) -> left));
    }

    private Map<Long, String> loadMoldCodes(Collection<Product> products) {
        if (requirementFormRepository == null) {
            return Map.of();
        }
        List<Long> projectIds = products.stream()
            .filter(product -> TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT.equals(product.getProductType()))
            .map(Product::getProductId)
            .filter(Objects::nonNull)
            .toList();
        if (projectIds.isEmpty()) {
            return Map.of();
        }
        return requirementFormRepository.selectList(new LambdaQueryWrapper<RequirementForm>()
                .in(RequirementForm::getProjectId, projectIds)
                .eq(RequirementForm::getDeletedFlag, 0))
            .stream()
            .filter(form -> StringUtils.hasText(form.getMoldCodes()))
            .collect(Collectors.toMap(RequirementForm::getProjectId, RequirementForm::getMoldCodes, (left, right) -> left));
    }

    private ProjectColorSummaryVO buildColorSummary(Product product) {
        if (!TimelineNodeConstants.PRODUCT_TYPE_PRODUCT_LINE.equals(product.getProductType())) {
            return ProjectColorSummaryVO.builder()
                .skuColorCount(0)
                .productionColorCount(0)
                .skuColors(List.of())
                .productionColors(List.of())
                .skuOnlyColors(List.of())
                .productionOnlyColors(List.of())
                .build();
        }

        List<Product> skuProducts = productRepository.selectList(new LambdaQueryWrapper<Product>()
            .eq(Product::getParentProductId, product.getProductId())
            .in(Product::getProductType, TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT, TimelineNodeConstants.PRODUCT_TYPE_SKU)
            .eq(Product::getDeletedFlag, 0)
            .orderByAsc(Product::getColorCode)
            .orderByAsc(Product::getColor));
        List<ProductProductionColorDecision> decisions = colorDecisionRepository == null ? List.of() : colorDecisionRepository.selectList(
            new LambdaQueryWrapper<ProductProductionColorDecision>()
                .eq(ProductProductionColorDecision::getProductId, product.getProductId())
                .eq(ProductProductionColorDecision::getSelectedFlag, 1)
                .eq(ProductProductionColorDecision::getStatus, "confirmed")
                .eq(ProductProductionColorDecision::getDeletedFlag, 0)
                .orderByAsc(ProductProductionColorDecision::getColorCode)
                .orderByAsc(ProductProductionColorDecision::getColorName));

        Map<String, String> dictionaryNames = loadColorDictionaryNames(skuProducts, decisions);
        Map<String, ProjectColorSummaryVO.ColorUsageVO> skuColors = new LinkedHashMap<>();
        for (Product sku : safeList(skuProducts)) {
            String key = colorKey(sku.getColorCode(), sku.getColor());
            if (!StringUtils.hasText(key)) continue;
            ProjectColorSummaryVO.ColorUsageVO current = skuColors.get(key);
            if (current == null) {
                skuColors.put(key, ProjectColorSummaryVO.ColorUsageVO.builder()
                    .colorCode(sku.getColorCode())
                    .colorName(resolveColorName(sku.getColorCode(), sku.getColor(), dictionaryNames))
                    .skuCount(1)
                    .decisionCount(0)
                    .build());
            } else {
                current.setSkuCount(current.getSkuCount() + 1);
            }
        }

        Map<String, ProjectColorSummaryVO.ColorUsageVO> productionColors = new LinkedHashMap<>();
        for (ProductProductionColorDecision decision : safeList(decisions)) {
            String key = colorKey(decision.getColorCode(), decision.getColorName());
            if (!StringUtils.hasText(key)) continue;
            ProjectColorSummaryVO.ColorUsageVO current = productionColors.get(key);
            if (current == null) {
                productionColors.put(key, ProjectColorSummaryVO.ColorUsageVO.builder()
                    .colorCode(decision.getColorCode())
                    .colorName(resolveColorName(decision.getColorCode(), decision.getColorName(), dictionaryNames))
                    .skuCount(0)
                    .decisionCount(1)
                    .build());
            } else {
                current.setDecisionCount(current.getDecisionCount() + 1);
            }
        }

        List<ProjectColorSummaryVO.ColorUsageVO> skuOnly = skuColors.entrySet().stream()
            .filter(entry -> !productionColors.containsKey(entry.getKey()))
            .map(Map.Entry::getValue)
            .toList();
        List<ProjectColorSummaryVO.ColorUsageVO> productionOnly = productionColors.entrySet().stream()
            .filter(entry -> !skuColors.containsKey(entry.getKey()))
            .map(Map.Entry::getValue)
            .toList();

        return ProjectColorSummaryVO.builder()
            .skuColorCount(skuColors.size())
            .productionColorCount(productionColors.size())
            .skuColors(new ArrayList<>(skuColors.values()))
            .productionColors(new ArrayList<>(productionColors.values()))
            .skuOnlyColors(skuOnly)
            .productionOnlyColors(productionOnly)
            .build();
    }

    private Map<String, String> loadColorDictionaryNames(List<Product> skuProducts, List<ProductProductionColorDecision> decisions) {
        if (codeItemRepository == null) return Map.of();
        Set<String> codes = new java.util.LinkedHashSet<>();
        safeList(skuProducts).stream().map(Product::getColorCode).filter(StringUtils::hasText).forEach(codes::add);
        safeList(decisions).stream().map(ProductProductionColorDecision::getColorCode).filter(StringUtils::hasText).forEach(codes::add);
        if (codes.isEmpty()) return Map.of();
        return codeItemRepository.selectList(new LambdaQueryWrapper<CodeItem>()
                .eq(CodeItem::getCodeType, "color")
                .in(CodeItem::getCodeValue, codes)
                .eq(CodeItem::getDeletedFlag, 0))
            .stream()
            .filter(item -> StringUtils.hasText(item.getCodeValue()))
            .collect(Collectors.toMap(CodeItem::getCodeValue, CodeItem::getCodeName, (left, right) -> left));
    }

    private String resolveColorName(String colorCode, String fallbackName, Map<String, String> dictionaryNames) {
        String dictName = StringUtils.hasText(colorCode) ? dictionaryNames.get(colorCode) : null;
        if (StringUtils.hasText(dictName)) return dictName;
        if (StringUtils.hasText(fallbackName)) return fallbackName;
        return StringUtils.hasText(colorCode) ? colorCode : "--";
    }

    private String colorKey(String colorCode, String colorName) {
        if (StringUtils.hasText(colorCode)) return colorCode.trim();
        return StringUtils.hasText(colorName) ? colorName.trim() : "";
    }

    private <T> List<T> safeList(List<T> source) {
        return source == null ? List.of() : source.stream()
            .filter(Objects::nonNull)
            .sorted(Comparator.comparing(item -> item instanceof Product value ? colorKey(value.getColorCode(), value.getColor())
                : item instanceof ProductProductionColorDecision value ? colorKey(value.getColorCode(), value.getColorName())
                : ""))
            .toList();
    }

    private String ownerName(Product product, Map<Long, String> ownerNames) {
        return product.getOwnerUserId() == null ? null : ownerNames.get(product.getOwnerUserId());
    }

    private Product getProductOrThrow(Long projectId) {
        Product product = productRepository.selectById(projectId);
        if (product == null || Integer.valueOf(1).equals(product.getDeletedFlag())) {
            throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "项目不存在");
        }
        return product;
    }

    private Integer normalizeStepNo(Product product, Integer currentStepNo) {
        if (currentStepNo == null || currentStepNo < 1) {
            return 1;
        }
        int maxStepNo = timelineDefinitionProvider.getDefinitions(product).size();
        return Math.min(currentStepNo, maxStepNo);
    }

    private String currentNodeName(Product product, Integer currentStepNo) {
        if (TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT.equals(product.getProductType())
            && ProductStatusConstants.ARCHIVED.equals(product.getStatus())) {
            return "已完结";
        }
        return timelineDefinitionProvider.getCurrentNodeName(product, currentStepNo);
    }

    private String productTypeName(String productType) {
        if (TimelineNodeConstants.PRODUCT_TYPE_PRODUCT_LINE.equals(productType)) {
            return TimelineNodeConstants.PRODUCT_TYPE_NAME_PRODUCT_LINE;
        }
        if (TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT.equals(productType)) {
            return TimelineNodeConstants.PRODUCT_TYPE_NAME_MODEL_VARIANT;
        }
        if (TimelineNodeConstants.PRODUCT_TYPE_SKU.equals(productType)) {
            return TimelineNodeConstants.PRODUCT_TYPE_NAME_SKU;
        }
        return productType;
    }

    private String statusName(String status) {
        return switch (status) {
            case ProductStatusConstants.DRAFT -> "草稿";
            case ProductStatusConstants.DEVELOPING -> "开发中";
            case ProductStatusConstants.RELEASED -> "已发布";
            case ProductStatusConstants.ARCHIVED -> "已归档";
            default -> status;
        };
    }
}
