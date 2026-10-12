package com.yuewei.plm.module.bom.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.module.bom.entity.ProductBom;
import com.yuewei.plm.module.bom.service.BomAmountPolicy;
import com.yuewei.plm.module.pilot.PilotAccessService;
import com.yuewei.plm.module.bom.entity.ProductBomCostSnapshot;
import com.yuewei.plm.module.bom.entity.ProductBomItem;
import com.yuewei.plm.module.bom.entity.ProductBomRoute;
import com.yuewei.plm.module.bom.entity.ProductBomRouteColor;
import com.yuewei.plm.module.bom.entity.ProductBomRouteFormalSelection;
import com.yuewei.plm.module.bom.repository.ProductBomCostSnapshotRepository;
import com.yuewei.plm.module.bom.repository.ProductBomItemRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteColorRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteFormalSelectionRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteRepository;
import com.yuewei.plm.module.bom.vo.BomHistoryMergeCandidateVO;
import com.yuewei.plm.module.bom.vo.BomHistoryMergeResultVO;
import com.yuewei.plm.module.operationlog.constant.OperationActionConstants;
import com.yuewei.plm.module.operationlog.service.OperationLogCreateCommand;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import jakarta.servlet.http.HttpServletRequest;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

@Service
@RequiredArgsConstructor
public class HistoricalBomMergeService {

    private static final String STATUS_ACTIVE = "active";
    private static final String STATUS_RELEASED = "released";
    private static final String STATUS_ARCHIVED = "archived";
    private static final String STATUS_INVALIDATED = "invalidated";
    private static final List<String> MERGE_STATUSES = List.of("draft", STATUS_RELEASED);
    private static final List<String> COLOR_KEYWORDS = List.of(
        "色粉", "色母", "颜料", "色浆", "color powder", "masterbatch", "pigment", "colorant"
    );

    private final ProductRepository productRepository;
    private final ProductBomRepository productBomRepository;
    private final ProductBomRouteRepository productBomRouteRepository;
    private final ProductBomRouteColorRepository productBomRouteColorRepository;
    private final ProductBomItemRepository productBomItemRepository;
    private final ProductBomCostSnapshotRepository productBomCostSnapshotRepository;
    private final ProductBomRouteFormalSelectionRepository productBomRouteFormalSelectionRepository;
    private final OperationLogService operationLogService;
    private final PilotAccessService access;

    public BomHistoryMergeResultVO analyze(Long productId) {
        List<MergeGroup> groups = loadGroups(productId);
        return buildResult(groups, List.of());
    }

    @Transactional
    public BomHistoryMergeResultVO autoMerge(Long productId, HttpServletRequest request) {
        access.requirePermission("bom:write");
        if (productId != null) access.requireProduct(productId);
        List<MergeGroup> groups = loadGroups(productId);
        List<MergeGroup> mergeable = groups.stream()
            .filter(group -> Boolean.TRUE.equals(group.analysis().getCanAutoMerge()))
            .toList();
        mergeable.stream().flatMap(group -> group.bundles().stream()).map(bundle -> bundle.bom().getProductId()).distinct().forEach(access::requireProduct);
        if (mergeable.stream().flatMap(group -> group.bundles().stream()).flatMap(bundle -> bundle.items().stream()).anyMatch(BomAmountPolicy::priced)) access.requireFinanceWrite();
        List<BomHistoryMergeCandidateVO> merged = new ArrayList<>();
        int archivedBomCount = 0;
        for (MergeGroup group : mergeable) {
            MergeOutcome outcome = mergeGroup(group, request);
            merged.add(outcome.candidate());
            archivedBomCount += outcome.archivedBomCount();
        }
        return buildResult(groups, merged, mergeable.size(), archivedBomCount);
    }

    private BomHistoryMergeResultVO buildResult(List<MergeGroup> groups, List<BomHistoryMergeCandidateVO> merged) {
        return buildResult(groups, merged, 0, 0);
    }

    private BomHistoryMergeResultVO buildResult(List<MergeGroup> groups, List<BomHistoryMergeCandidateVO> merged,
                                                int autoMergedGroupCount, int archivedBomCount) {
        List<BomHistoryMergeCandidateVO> candidates = groups.stream().map(MergeGroup::analysis).toList();
        long autoMergeable = candidates.stream().filter(item -> Boolean.TRUE.equals(item.getCanAutoMerge())).count();
        return BomHistoryMergeResultVO.builder()
            .analyzedGroupCount(groups.size())
            .autoMergeableGroupCount((int) autoMergeable)
            .autoMergedGroupCount(autoMergedGroupCount)
            .archivedBomCount(archivedBomCount)
            .candidates(candidates)
            .mergedGroups(merged)
            .build();
    }

    private List<MergeGroup> loadGroups(Long productId) {
        List<ProductBom> boms = productBomRepository.selectList(new LambdaQueryWrapper<ProductBom>()
            .eq(productId != null, ProductBom::getProductId, productId)
            .in(ProductBom::getStatus, MERGE_STATUSES)
            .eq(ProductBom::getDeletedFlag, 0));
        if (boms == null || boms.isEmpty()) {
            return List.of();
        }
        List<Long> bomIds = boms.stream().map(ProductBom::getProductBomId).toList();
        List<ProductBomRoute> routes = productBomRouteRepository.selectList(new LambdaQueryWrapper<ProductBomRoute>()
            .in(ProductBomRoute::getProductBomId, bomIds)
            .eq(ProductBomRoute::getStatus, STATUS_ACTIVE)
            .eq(ProductBomRoute::getDeletedFlag, 0));
        if (routes == null || routes.isEmpty()) {
            return List.of();
        }
        Map<Long, List<ProductBomRoute>> routesByBom = routes.stream()
            .collect(Collectors.groupingBy(ProductBomRoute::getProductBomId, LinkedHashMap::new, Collectors.toList()));
        Map<Long, List<ProductBomRouteColor>> colorsByRoute = loadColors(routes);
        Map<Long, List<ProductBomItem>> itemsByRoute = loadItems(routes);
        Map<String, List<RouteBundle>> groups = new LinkedHashMap<>();
        for (ProductBom bom : boms) {
            List<ProductBomRoute> bomRoutes = routesByBom.getOrDefault(bom.getProductBomId(), List.of());
            if (bomRoutes.size() != 1) {
                continue;
            }
            ProductBomRoute route = bomRoutes.get(0);
            RouteBundle bundle = new RouteBundle(
                bom,
                route,
                colorsByRoute.getOrDefault(route.getProductBomRouteId(), List.of()),
                itemsByRoute.getOrDefault(route.getProductBomRouteId(), List.of())
            );
            String key = groupKey(bom, route);
            groups.computeIfAbsent(key, ignored -> new ArrayList<>()).add(bundle);
        }
        List<MergeGroup> result = new ArrayList<>();
        for (List<RouteBundle> bundles : groups.values()) {
            if (bundles.size() < 2) {
                continue;
            }
            result.add(new MergeGroup(analyzeBundles(bundles), bundles));
        }
        return result;
    }

    private Map<Long, List<ProductBomRouteColor>> loadColors(List<ProductBomRoute> routes) {
        List<Long> routeIds = routes.stream().map(ProductBomRoute::getProductBomRouteId).toList();
        List<ProductBomRouteColor> colors = productBomRouteColorRepository.selectList(new LambdaQueryWrapper<ProductBomRouteColor>()
            .in(ProductBomRouteColor::getProductBomRouteId, routeIds)
            .eq(ProductBomRouteColor::getStatus, STATUS_ACTIVE)
            .eq(ProductBomRouteColor::getDeletedFlag, 0));
        return colors == null ? Map.of() : colors.stream()
            .collect(Collectors.groupingBy(ProductBomRouteColor::getProductBomRouteId, LinkedHashMap::new, Collectors.toList()));
    }

    private Map<Long, List<ProductBomItem>> loadItems(List<ProductBomRoute> routes) {
        List<Long> routeIds = routes.stream().map(ProductBomRoute::getProductBomRouteId).toList();
        List<ProductBomItem> items = productBomItemRepository.selectList(new LambdaQueryWrapper<ProductBomItem>()
            .in(ProductBomItem::getProductBomRouteId, routeIds)
            .eq(ProductBomItem::getDeletedFlag, 0));
        return items == null ? Map.of() : items.stream()
            .collect(Collectors.groupingBy(ProductBomItem::getProductBomRouteId, LinkedHashMap::new, Collectors.toList()));
    }

    private BomHistoryMergeCandidateVO analyzeBundles(List<RouteBundle> bundles) {
        RouteBundle reference = selectMainBundle(bundles);
        Product product = productRepository.selectById(reference.bom().getProductId());
        if (bundles.stream().map(bundle -> normalize(bundle.bom().getBomType())).distinct().count() > 1) {
            return buildCandidate(product, bundles, reference, "high", false, "BOM type mismatch");
        }
        if (bundles.stream().map(bundle -> normalize(bundle.bom().getBomScope())).distinct().count() > 1) {
            return buildCandidate(product, bundles, reference, "high", false, "BOM scope mismatch");
        }
        if (bundles.stream().map(bundle -> normalize(bundle.bom().getStatus())).distinct().count() > 1) {
            return buildCandidate(product, bundles, reference, "high", false, "BOM status mismatch");
        }
        if (bundles.stream().map(bundle -> routeKey(bundle.route())).distinct().count() > 1) {
            return buildCandidate(product, bundles, reference, "high", false, "Route mismatch");
        }
        if (bundles.stream().anyMatch(bundle -> bundle.colors().stream()
            .map(color -> colorKey(color.getColorCode(), color.getColorName()))
            .distinct().count() != bundle.colors().size())) {
            return buildCandidate(product, bundles, reference, "high", false, "Duplicate color code/name in one BOM");
        }
        if (bundles.stream().anyMatch(bundle -> bundle.items().isEmpty())) {
            return buildCandidate(product, bundles, reference, "high", false, "Missing BOM items");
        }

        Set<String> commonReference = commonItemSignatures(bundles.get(0));
        Set<String> fullReference = fullItemSignatures(bundles.get(0));
        boolean commonEqual = true;
        boolean fullEqual = true;
        Map<String, Set<Long>> itemToBoms = new LinkedHashMap<>();
        for (RouteBundle bundle : bundles) {
            commonEqual &= commonReference.equals(commonItemSignatures(bundle));
            fullEqual &= fullReference.equals(fullItemSignatures(bundle));
            for (ProductBomItem item : bundle.items()) {
                itemToBoms.computeIfAbsent(itemSignature(item), ignored -> new LinkedHashSet<>())
                    .add(bundle.bom().getProductBomId());
            }
        }
        int commonItemCount = commonReference.size();
        int colorDiffItemCount = (int) itemToBoms.values().stream().filter(ids -> ids.size() < bundles.size()).count();
        List<String> colors = bundles.stream()
            .flatMap(bundle -> bundle.colors().stream())
            .map(color -> trim(color.getColorName()))
            .filter(StringUtils::hasText)
            .distinct()
            .toList();
        if (colors.size() < 2) {
            return buildCandidate(product, bundles, reference, "medium", false, "Not enough colors to merge");
        }
        if (!commonEqual) {
            return buildCandidate(product, bundles, reference, "high", false, "Main structure mismatch");
        }
        if (!fullEqual) {
            return buildCandidate(product, bundles, reference, "medium", false, "Color-related item differences require manual review");
        }
        return buildCandidate(product, bundles, reference, "low", true, "Full item signature matched and colors can be merged", commonItemCount, colorDiffItemCount);
    }

    private BomHistoryMergeCandidateVO buildCandidate(Product product, List<RouteBundle> bundles, RouteBundle reference,
                                                      String riskLevel, boolean canAutoMerge, String reason) {
        return buildCandidate(product, bundles, reference, riskLevel, canAutoMerge, reason,
            commonItemSignatures(bundles.get(0)).size(), 0);
    }

    private BomHistoryMergeCandidateVO buildCandidate(Product product, List<RouteBundle> bundles, RouteBundle reference,
                                                      String riskLevel, boolean canAutoMerge, String reason,
                                                      int commonItemCount, int colorDiffItemCount) {
        return BomHistoryMergeCandidateVO.builder()
            .productId(product == null ? reference.bom().getProductId() : product.getProductId())
            .productCode(product == null ? null : product.getProductCode())
            .productName(product == null ? null : product.getProductName())
            .processId(reference.route().getProcessId())
            .routeName(reference.route().getRouteName())
            .routeVariantNo(reference.route().getRouteVariantNo())
            .bomType(reference.bom().getBomType())
            .candidateBomIds(bundles.stream().map(bundle -> bundle.bom().getProductBomId()).toList())
            .candidateVersions(bundles.stream().map(bundle -> trim(bundle.bom().getVersionNo())).distinct().toList())
            .colors(bundles.stream()
                .flatMap(bundle -> bundle.colors().stream())
                .map(color -> trim(color.getColorName()))
                .filter(StringUtils::hasText)
                .distinct()
                .toList())
            .commonItemCount(commonItemCount)
            .colorDiffItemCount(colorDiffItemCount)
            .riskLevel(riskLevel)
            .canAutoMerge(canAutoMerge)
            .reason(reason)
            .mainProductBomId(reference.bom().getProductBomId())
            .mainProductBomRouteId(reference.route().getProductBomRouteId())
            .build();
    }

    private MergeOutcome mergeGroup(MergeGroup group, HttpServletRequest request) {
        RouteBundle main = selectMainBundle(group.bundles());
        LocalDateTime now = LocalDateTime.now();
        String operator = access.actor().username();
        String mergedFrom = "mergedFromProductBomIds=" + group.analysis().getCandidateBomIds()
            + "; mergedFromVersions=" + group.analysis().getCandidateVersions();
        String mergedTo = "mergedToProductBomId=" + main.bom().getProductBomId()
            + "; mergedToProductBomRouteId=" + main.route().getProductBomRouteId();
        appendRemark(main.bom(), mergedFrom + "; costReviewRequired=true");
        main.bom().setUpdatedAt(now);
        main.bom().setUpdatedBy(operator);
        productBomRepository.updateById(main.bom());

        int archivedBomCount = 0;
        for (RouteBundle bundle : group.bundles()) {
            if (bundle.bom().getProductBomId().equals(main.bom().getProductBomId())) {
                continue;
            }
            appendRemark(bundle.bom(), mergedTo);
            bundle.bom().setStatus(STATUS_ARCHIVED);
            bundle.bom().setUpdatedAt(now);
            bundle.bom().setUpdatedBy(operator);
            productBomRepository.updateById(bundle.bom());
            productBomCostSnapshotRepository.update(null, new UpdateWrapper<ProductBomCostSnapshot>()
                .set("status", STATUS_ARCHIVED)
                .set("updated_at", now)
                .set("updated_by", operator)
                .eq("product_bom_id", bundle.bom().getProductBomId())
                .eq("deleted_flag", 0));
            archivedBomCount++;
        }
        mergeColors(main, group.bundles(), now, operator);
        mergeFormalSelections(main, now, operator, mergedTo);
        writeOperationLog(main, group, request);
        return new MergeOutcome(group.analysis(), archivedBomCount);
    }

    private void mergeColors(RouteBundle main, List<RouteBundle> bundles, LocalDateTime now, String operator) {
        Map<String, ProductBomRouteColor> existing = productBomRouteColorRepository.selectList(new LambdaQueryWrapper<ProductBomRouteColor>()
                .eq(ProductBomRouteColor::getProductBomRouteId, main.route().getProductBomRouteId())
                .eq(ProductBomRouteColor::getDeletedFlag, 0))
            .stream()
            .collect(Collectors.toMap(color -> colorKey(color.getColorCode(), color.getColorName()), color -> color, (left, right) -> left, LinkedHashMap::new));
        for (RouteBundle bundle : bundles) {
            for (ProductBomRouteColor color : bundle.colors()) {
                String key = colorKey(color.getColorCode(), color.getColorName());
                if (existing.containsKey(key)) {
                    continue;
                }
                ProductBomRouteColor copy = new ProductBomRouteColor();
                copy.setProductBomId(main.bom().getProductBomId());
                copy.setProductBomRouteId(main.route().getProductBomRouteId());
                copy.setCodeItemId(color.getCodeItemId());
                copy.setColorCode(trim(color.getColorCode()));
                copy.setColorName(trim(color.getColorName()));
                copy.setStatus(STATUS_ACTIVE);
                copy.setCreatedAt(now);
                copy.setCreatedBy(operator);
                copy.setUpdatedAt(now);
                copy.setUpdatedBy(operator);
                copy.setDeletedFlag(0);
                productBomRouteColorRepository.insert(copy);
                existing.put(key, copy);
            }
        }
    }

    private void mergeFormalSelections(RouteBundle main, LocalDateTime now, String operator, String mergedTo) {
        List<ProductBomRouteFormalSelection> activeSelections = productBomRouteFormalSelectionRepository.selectList(
            new LambdaQueryWrapper<ProductBomRouteFormalSelection>()
                .eq(ProductBomRouteFormalSelection::getProductId, main.bom().getProductId())
                .eq(ProductBomRouteFormalSelection::getProcessId, main.route().getProcessId())
                .eq(ProductBomRouteFormalSelection::getStatus, STATUS_ACTIVE)
                .eq(ProductBomRouteFormalSelection::getDeletedFlag, 0));
        boolean mainSelectionExists = false;
        for (ProductBomRouteFormalSelection selection : activeSelections) {
            if (main.bom().getProductBomId().equals(selection.getProductBomId())
                && main.route().getProductBomRouteId().equals(selection.getProductBomRouteId())) {
                mainSelectionExists = true;
                appendRemark(selection, mergedTo);
                selection.setUpdatedAt(now);
                selection.setUpdatedBy(operator);
                productBomRouteFormalSelectionRepository.updateById(selection);
                continue;
            }
            selection.setStatus(STATUS_INVALIDATED);
            selection.setInvalidatedAt(now);
            selection.setInvalidatedReason(mergedTo);
            appendRemark(selection, mergedTo);
            selection.setUpdatedAt(now);
            selection.setUpdatedBy(operator);
            productBomRouteFormalSelectionRepository.updateById(selection);
        }
        if (!mainSelectionExists) {
            ProductBomRouteFormalSelection selection = new ProductBomRouteFormalSelection();
            selection.setProductId(main.bom().getProductId());
            selection.setProductBomId(main.bom().getProductBomId());
            selection.setProductBomRouteId(main.route().getProductBomRouteId());
            selection.setProcessId(main.route().getProcessId());
            selection.setBomVersionNo(main.bom().getVersionNo());
            selection.setSelectionBatchNo("MERGE-" + main.bom().getProductBomId() + "-" + now.toString().replace(':', '-'));
            selection.setStatus(STATUS_ACTIVE);
            selection.setConfirmedAt(now);
            selection.setConfirmedBy(operator);
            selection.setRemark(mergedTo);
            selection.setCreatedAt(now);
            selection.setCreatedBy(operator);
            selection.setUpdatedAt(now);
            selection.setUpdatedBy(operator);
            selection.setDeletedFlag(0);
            productBomRouteFormalSelectionRepository.insert(selection);
        }
    }

    private void writeOperationLog(RouteBundle main, MergeGroup group, HttpServletRequest request) {
        if (operationLogService == null) {
            return;
        }
        operationLogService.logSuccess(OperationLogCreateCommand.builder()
            .action(OperationActionConstants.BOM_HISTORY_MERGE)
            .businessType("ProductBom")
            .businessId(String.valueOf(main.bom().getProductBomId()))
            .businessCode(main.bom().getBomCode())
            .businessName(main.bom().getBomName())
            .detailJson("{\"candidateBomIds\":\"" + group.analysis().getCandidateBomIds() + "\",\"riskLevel\":\""
                + group.analysis().getRiskLevel() + "\"}")
            .request(request)
            .build());
    }

    private RouteBundle selectMainBundle(List<RouteBundle> bundles) {
        return bundles.stream()
            .sorted(Comparator
                .comparing((RouteBundle bundle) -> STATUS_RELEASED.equals(normalize(bundle.bom().getStatus())) ? 0 : 1)
                .thenComparing(bundle -> bundle.bom().getReleasedAt(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(bundle -> bundle.bom().getVersionNo(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(bundle -> bundle.bom().getProductBomId(), Comparator.reverseOrder()))
            .findFirst()
            .orElseThrow(() -> new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "No mergeable main BOM"));
    }

    private Set<String> commonItemSignatures(RouteBundle bundle) {
        return bundle.items().stream()
            .filter(item -> !isColorRelatedItem(item))
            .map(this::itemSignature)
            .collect(Collectors.toCollection(LinkedHashSet::new));
    }

    private Set<String> fullItemSignatures(RouteBundle bundle) {
        return bundle.items().stream()
            .map(this::itemSignature)
            .collect(Collectors.toCollection(LinkedHashSet::new));
    }

    private String itemSignature(ProductBomItem item) {
        return String.join("|",
            trim(item.getItemCode()),
            trim(item.getItemName()),
            trim(item.getSpecification()),
            trim(item.getUnit()),
            item.getQuantity() == null ? "" : item.getQuantity().stripTrailingZeros().toPlainString(),
            item.getLineNo() == null ? "" : String.valueOf(item.getLineNo()),
            trim(item.getMaterialSource()));
    }

    private boolean isColorRelatedItem(ProductBomItem item) {
        String text = (trim(item.getItemCode()) + " " + trim(item.getItemName()) + " " + trim(item.getSpecification())).toLowerCase();
        return COLOR_KEYWORDS.stream().anyMatch(text::contains);
    }

    private String groupKey(ProductBom bom, ProductBomRoute route) {
        return String.join("|",
            String.valueOf(bom.getProductId()),
            normalize(route.getProcessId() == null ? null : String.valueOf(route.getProcessId())),
            normalize(route.getRouteVariantNo()),
            normalize(bom.getBomType()),
            normalize(bom.getBomScope()),
            normalize(bom.getStatus()));
    }

    private String routeKey(ProductBomRoute route) {
        return String.join("|",
            normalize(route.getProcessId() == null ? null : String.valueOf(route.getProcessId())),
            normalize(route.getRouteVariantNo()),
            normalize(route.getRouteCode()),
            normalize(route.getRouteName()));
    }

    private String colorKey(String colorCode, String colorName) {
        return trim(colorCode) + "|" + trim(colorName);
    }

    private void appendRemark(ProductBom bom, String addition) {
        bom.setRemark(appendRemarkText(bom.getRemark(), addition));
    }

    private void appendRemark(ProductBomRouteFormalSelection selection, String addition) {
        selection.setRemark(appendRemarkText(selection.getRemark(), addition));
    }

    private String appendRemarkText(String original, String addition) {
        if (!StringUtils.hasText(addition)) {
            return original;
        }
        if (!StringUtils.hasText(original)) {
            return addition;
        }
        if (original.contains(addition)) {
            return original;
        }
        return original + "; " + addition;
    }

    private String normalize(String value) {
        return value == null ? "" : value.trim().toLowerCase();
    }

    private String trim(String value) {
        return value == null ? "" : value.trim();
    }

    private record RouteBundle(
        ProductBom bom,
        ProductBomRoute route,
        List<ProductBomRouteColor> colors,
        List<ProductBomItem> items
    ) {
    }

    private record MergeGroup(BomHistoryMergeCandidateVO analysis, List<RouteBundle> bundles) {
    }

    private record MergeOutcome(BomHistoryMergeCandidateVO candidate, int archivedBomCount) {
    }
}
