package com.yuewei.plm.module.bom.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.module.bom.entity.ProductBom;
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
import com.yuewei.plm.module.bom.service.BomLedgerService;
import com.yuewei.plm.module.bom.vo.BomLedgerRowVO;
import com.yuewei.plm.module.bom.vo.BomSkuRowVO;
import com.yuewei.plm.module.bom.vo.BomSummaryVO;
import com.yuewei.plm.module.bom.vo.ProductBomCostSnapshotVO;
import com.yuewei.plm.module.bom.vo.ProductBomItemVO;
import com.yuewei.plm.module.bom.vo.ProductBomRouteVO;
import com.yuewei.plm.module.bom.vo.ProductBomWorkbenchVO;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

@Service
@RequiredArgsConstructor
public class BomLedgerServiceImpl implements BomLedgerService {
    private final ProductRepository productRepository;
    private final ProductBomRepository bomRepository;
    private final ProductBomRouteRepository routeRepository;
    private final ProductBomRouteColorRepository colorRepository;
    private final ProductBomItemRepository itemRepository;
    private final ProductBomCostSnapshotRepository costRepository;
    private final ProductBomRouteFormalSelectionRepository formalSelectionRepository;

    @Override
    public List<BomLedgerRowVO> listFormal() {
        List<ProductBom> boms = safe(bomRepository.selectList(new LambdaQueryWrapper<ProductBom>()
            .eq(ProductBom::getBomScope, "formal").eq(ProductBom::getDeletedFlag, 0)
            .eq(ProductBom::getStatus, "released")
            .orderByDesc(ProductBom::getUpdatedAt)));
        Set<Long> activeFormalBomIds = activeFormalBomIds();
        return describeFormal(boms.stream().filter(bom -> isLedgerVisible(bom, activeFormalBomIds)).toList());
    }

    @Override
    public List<BomLedgerRowVO> describeFormal(List<ProductBom> boms) {
        BatchData batch = loadBatch(boms, true, false, false);
        return boms.stream().map(bom -> {
            Product product = batch.products().get(bom.getProductId());
            return BomLedgerRowVO.builder()
                .productBomId(bom.getProductBomId()).productId(bom.getProductId()).bomCode(bom.getBomCode())
                .productCode(product == null ? null : product.getProductCode())
                .productName(product == null ? null : product.getProductName())
                .model(product == null ? null : product.getModel()).versionNo(bom.getVersionNo())
                .routeCount(batch.routesFor(bom.getProductBomId()).size())
                .skuCount(countSkusWithoutConflict(bom, batch)).status(bom.getStatus())
                .sourceType(bom.getSourceType()).updatedAt(bom.getUpdatedAt()).build();
        }).toList();
    }

    private boolean isLedgerVisible(ProductBom bom, Set<Long> activeFormalBomIds) {
        if (!"formal".equals(bom.getBomScope()) || !"released".equals(bom.getStatus())) return false;
        if ("import".equals(bom.getSourceType()) || "history-import".equals(bom.getReleasedBy())) return true;
        return activeFormalBomIds.contains(bom.getProductBomId());
    }

    private Set<Long> activeFormalBomIds() {
        return safe(formalSelectionRepository.selectList(new LambdaQueryWrapper<ProductBomRouteFormalSelection>()
            .eq(ProductBomRouteFormalSelection::getStatus, "active")
            .eq(ProductBomRouteFormalSelection::getDeletedFlag, 0)))
            .stream()
            .filter(selection -> "active".equals(selection.getStatus()))
            .map(ProductBomRouteFormalSelection::getProductBomId)
            .collect(java.util.stream.Collectors.toSet());
    }

    @Override
    public ProductBomWorkbenchVO getWorkbench(Long bomId) {
        ProductBom bom = requireBom(bomId);
        return buildWorkbench(bom, loadBatch(List.of(bom), false, true, true));
    }

    private ProductBomWorkbenchVO buildWorkbench(ProductBom bom, BatchData batch) {
        Long bomId = bom.getProductBomId();
        List<ProductBomRouteVO> routeVOs = batch.routesFor(bomId).stream().map(route ->
            ProductBomRouteVO.builder()
                .productBomRouteId(route.getProductBomRouteId()).productBomId(bomId)
                .processId(route.getProcessId()).routeCode(route.getRouteCode()).routeName(route.getRouteName())
                .sharedBomGroupCode(route.getSharedBomGroupCode()).routeVariantNo(route.getRouteVariantNo())
                .variantName(route.getVariantName()).sourceProductBomRouteId(route.getSourceProductBomRouteId())
                .status(route.getStatus()).colors(batch.colorsFor(route.getProductBomRouteId()).stream()
                    .map(ProductBomRouteColor::getColorName).toList())
                .colorItems(batch.colorsFor(route.getProductBomRouteId()).stream()
                    .map(com.yuewei.plm.module.bom.vo.ProductBomRouteColorVO::from).toList())
                .items(batch.itemsFor(route.getProductBomRouteId()).stream().map(ProductBomItemVO::from).toList())
                .costSnapshot(batch.costs().get(route.getProductBomRouteId()))
                .skuUnitCost(batch.costs().get(route.getProductBomRouteId()) == null
                    ? null : batch.costs().get(route.getProductBomRouteId()).getTotalCost()).build()
        ).toList();
        List<ProductBomItemVO> testItems = "test".equals(bom.getBomScope())
            ? batch.testItems().getOrDefault(bomId, List.of()).stream().map(ProductBomItemVO::from).toList()
            : List.of();
        BigDecimal currentSkuCost = averageRouteCost(routeVOs);
        return ProductBomWorkbenchVO.builder().productBomId(bomId).productId(bom.getProductId())
            .bomCode(bom.getBomCode()).bomName(bom.getBomName()).bomScope(bom.getBomScope())
            .versionNo(bom.getVersionNo()).status(bom.getStatus()).testTotalCost(bom.getTestTotalCost())
            .rdTotalCost(sumRouteCosts(routeVOs).add(bom.getTestTotalCost() == null ? BigDecimal.ZERO : bom.getTestTotalCost()))
            .formalAverageUnitCost("formal".equals(bom.getBomScope()) ? currentSkuCost : null)
            .currentBomSkuUnitCost(currentSkuCost)
            .calculatedAt(bom.getCalculatedAt()).testItems(testItems).routes(routeVOs).build();
    }

    @Override
    public List<BomSkuRowVO> listSkus(Long bomId) {
        ProductBom bom = requireBom(bomId);
        return buildSkus(bom, loadBatch(List.of(bom), true, false, true));
    }

    private List<BomSkuRowVO> buildSkus(ProductBom bom, BatchData batch) {
        List<ProductBomRoute> routes = batch.routesFor(bom.getProductBomId());
        ColorRouteIndex colorRouteIndex = indexRoutesByColor(routes, batch);
        List<Product> products = batch.children().getOrDefault(bom.getProductId(), List.of());
        if (products.isEmpty()) {
            Product owner = batch.products().get(bom.getProductId());
            if (owner != null && StringUtils.hasText(owner.getColor())) products = List.of(owner);
        }
        List<BomSkuRowVO> result = new ArrayList<>();
        for (Product product : products) {
            List<ProductBomRoute> matches = routesForProduct(product, colorRouteIndex);
            if (matches.size() > 1) {
                throw new BusinessException(ErrorCodeConstants.CODE_CONFLICT,
                    "颜色 " + product.getColor() + " 匹配到多条有效工艺路线");
            }
            ProductBomRoute route = matches.isEmpty() ? null : matches.get(0);
            result.add(BomSkuRowVO.builder().productId(product.getProductId()).skuCode(skuDisplayCode(product))
                .productName(product.getProductName()).phoneModel(product.getModel()).phoneModelCode(product.getPhoneModelCode())
                .color(product.getColor()).colorCode(product.getColorCode()).finishedProductCode(product.getFinishedProductCode())
                .status(product.getStatus()).productBomRouteId(route == null ? null : route.getProductBomRouteId())
                .routeCode(route == null ? null : route.getRouteCode())
                .sharedBomGroupCode(route == null ? null : route.getSharedBomGroupCode())
                .routeVariantNo(route == null ? null : route.getRouteVariantNo())
                .variantName(route == null ? null : route.getVariantName())
                .skuUnitCost(route == null || batch.costs().get(route.getProductBomRouteId()) == null
                    ? null : batch.costs().get(route.getProductBomRouteId()).getTotalCost()).build());
        }
        return result;
    }

    private String skuDisplayCode(Product product) {
        return product.getFinishedProductCode() != null && !product.getFinishedProductCode().isBlank()
            ? product.getFinishedProductCode()
            : product.getProductCode();
    }

    @Override
    public List<BomSkuRowVO> listSkusForRoute(Long routeId) {
        ProductBomRoute route = routeRepository.selectById(routeId);
        if (route == null || Integer.valueOf(1).equals(route.getDeletedFlag())) {
            throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "工艺路线不存在");
        }
        return listSkus(route.getProductBomId()).stream()
            .filter(sku -> routeId.equals(sku.getProductBomRouteId())).toList();
    }

    @Override
    public BomSummaryVO getSummary(Long productId) {
        List<ProductBom> values = safe(bomRepository.selectList(new LambdaQueryWrapper<ProductBom>()
            .eq(ProductBom::getProductId, productId).eq(ProductBom::getDeletedFlag, 0)
            .orderByDesc(ProductBom::getProductBomId)));
        ProductBom test = values.stream().filter(value -> "test".equals(value.getBomScope())).findFirst().orElse(null);
        BatchData batch = loadBatch(values, false, true, true);
        List<ProductBomWorkbenchVO> all = values.stream().filter(value -> !"test".equals(value.getBomScope()))
            .map(value -> buildWorkbench(value, batch)).toList();
        List<ProductBomWorkbenchVO> formal = all.stream().filter(value -> "formal".equals(value.getBomScope())).toList();
        BigDecimal rdTotalCost = values.stream().filter(value -> "test".equals(value.getBomScope()))
            .map(ProductBom::getTestTotalCost).filter(java.util.Objects::nonNull).reduce(BigDecimal.ZERO, BigDecimal::add);
        BigDecimal formalCost = BigDecimal.ZERO;
        int formalSkuCount = 0;
        for (ProductBomWorkbenchVO workbench : all) {
            BigDecimal routeTotal = sumRouteCosts(workbench.getRoutes());
            rdTotalCost = rdTotalCost.add(routeTotal);
            if ("formal".equals(workbench.getBomScope())) {
                for (ProductBomRouteVO route : workbench.getRoutes()) {
                    int colorCount = route.getColors() == null || route.getColors().isEmpty() ? 1 : route.getColors().size();
                    if (route.getSkuUnitCost() != null) {
                        formalCost = formalCost.add(route.getSkuUnitCost().multiply(BigDecimal.valueOf(colorCount)));
                        formalSkuCount += colorCount;
                    }
                }
            }
        }
        ProductBomWorkbenchVO current = all.isEmpty() ? null : all.get(0);
        return BomSummaryVO.builder().testTotalCost(test == null ? null : test.getTestTotalCost())
            .testCalculatedAt(test == null ? null : test.getCalculatedAt())
            .testVersionNo(test == null ? null : test.getVersionNo()).formalVersions(formal)
            .rdTotalCost(rdTotalCost)
            .formalAverageUnitCost(formalSkuCount == 0 ? null : formalCost.divide(BigDecimal.valueOf(formalSkuCount), 6, java.math.RoundingMode.HALF_UP))
            .currentBomSkuUnitCost(current == null ? null : current.getCurrentBomSkuUnitCost()).build();
    }

    private BigDecimal sumRouteCosts(List<ProductBomRouteVO> routes) {
        return routes.stream().map(ProductBomRouteVO::getSkuUnitCost).filter(java.util.Objects::nonNull)
            .reduce(BigDecimal.ZERO, BigDecimal::add);
    }

    private BigDecimal averageRouteCost(List<ProductBomRouteVO> routes) {
        if (routes.isEmpty()) return null;
        BigDecimal total = BigDecimal.ZERO;
        int count = 0;
        for (ProductBomRouteVO route : routes) {
            if (route.getSkuUnitCost() == null) continue;
            int colors = route.getColors() == null || route.getColors().isEmpty() ? 1 : route.getColors().size();
            total = total.add(route.getSkuUnitCost().multiply(BigDecimal.valueOf(colors)));
            count += colors;
        }
        return count == 0 ? null : total.divide(BigDecimal.valueOf(count), 6, java.math.RoundingMode.HALF_UP);
    }

    private ColorRouteIndex indexRoutesByColor(List<ProductBomRoute> routes, BatchData batch) {
        Map<String, List<ProductBomRoute>> byCode = new HashMap<>();
        Map<String, List<ProductBomRoute>> byName = new HashMap<>();
        for (ProductBomRoute route : routes) {
            for (ProductBomRouteColor color : batch.colorsFor(route.getProductBomRouteId())) {
                if (StringUtils.hasText(color.getColorCode())) {
                    byCode.computeIfAbsent(normalize(color.getColorCode()), key -> new ArrayList<>()).add(route);
                }
                if (StringUtils.hasText(color.getColorName())) {
                    byName.computeIfAbsent(normalize(color.getColorName()), key -> new ArrayList<>()).add(route);
                }
            }
        }
        return new ColorRouteIndex(byCode, byName);
    }

    private List<ProductBomRoute> routesForProduct(Product product, ColorRouteIndex colorRouteIndex) {
        if (StringUtils.hasText(product.getColorCode())) {
            return colorRouteIndex.byCode().getOrDefault(normalize(product.getColorCode()), List.of());
        }
        if (StringUtils.hasText(product.getColor())) {
            return colorRouteIndex.byName().getOrDefault(normalize(product.getColor()), List.of());
        }
        return List.of();
    }

    private String normalize(String value) {
        return value == null ? null : value.trim().toLowerCase(Locale.ROOT);
    }

    private record ColorRouteIndex(Map<String, List<ProductBomRoute>> byCode,
                                   Map<String, List<ProductBomRoute>> byName) {
    }

    private int countSkusWithoutConflict(ProductBom bom, BatchData batch) {
        try {
            return buildSkus(bom, batch).size();
        } catch (BusinessException exception) {
            return 0;
        }
    }

    private ProductBom requireBom(Long bomId) {
        ProductBom bom = bomRepository.selectById(bomId);
        if (bom == null || Integer.valueOf(1).equals(bom.getDeletedFlag())) {
            throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "BOM 不存在");
        }
        return bom;
    }

    /** Each relation is fetched at most once, independent of BOM, route and SKU counts. */
    private BatchData loadBatch(List<ProductBom> boms, boolean withProducts, boolean withItems, boolean withCosts) {
        Map<Long, List<ProductBomRoute>> routes = new HashMap<>();
        Map<Long, List<ProductBomRouteColor>> colors = new HashMap<>();
        Map<Long, List<ProductBomItem>> items = new HashMap<>();
        Map<Long, List<ProductBomItem>> testItems = new HashMap<>();
        Map<Long, ProductBomCostSnapshotVO> costs = new HashMap<>();
        Map<Long, Product> products = new HashMap<>();
        Map<Long, List<Product>> children = new HashMap<>();
        if (boms.isEmpty()) return new BatchData(routes, colors, items, testItems, costs, products, children);
        List<Long> bomIds = boms.stream().map(ProductBom::getProductBomId).distinct().toList();
        List<Long> ownerIds = boms.stream().map(ProductBom::getProductId).distinct().toList();
        List<ProductBomRoute> routeValues = safe(routeRepository.selectList(new LambdaQueryWrapper<ProductBomRoute>()
            .in(ProductBomRoute::getProductBomId, bomIds).eq(ProductBomRoute::getStatus, "active")
            .eq(ProductBomRoute::getDeletedFlag, 0).orderByAsc(ProductBomRoute::getProductBomRouteId)));
        routeValues.forEach(value -> routes.computeIfAbsent(value.getProductBomId(), key -> new ArrayList<>()).add(value));
        List<Long> routeIds = routeValues.stream().map(ProductBomRoute::getProductBomRouteId).toList();
        if (!routeIds.isEmpty()) {
            safe(colorRepository.selectList(new LambdaQueryWrapper<ProductBomRouteColor>()
                .in(ProductBomRouteColor::getProductBomRouteId, routeIds).eq(ProductBomRouteColor::getStatus, "active")
                .eq(ProductBomRouteColor::getDeletedFlag, 0).orderByAsc(ProductBomRouteColor::getProductBomRouteColorId)))
                .forEach(value -> colors.computeIfAbsent(value.getProductBomRouteId(), key -> new ArrayList<>()).add(value));
            if (withCosts) {
                safe(costRepository.selectList(new LambdaQueryWrapper<ProductBomCostSnapshot>()
                    .in(ProductBomCostSnapshot::getProductBomId, bomIds)
                    .in(ProductBomCostSnapshot::getProductBomRouteId, routeIds)
                    .in(ProductBomCostSnapshot::getStatus, List.of("current", "baseline"))
                    .eq(ProductBomCostSnapshot::getDeletedFlag, 0)
                    .orderByDesc(ProductBomCostSnapshot::getCalculatedAt, ProductBomCostSnapshot::getProductBomCostSnapshotId)))
                    .forEach(value -> costs.putIfAbsent(value.getProductBomRouteId(), toCostVo(value)));
            }
        }
        if (withItems) {
            safe(itemRepository.selectList(new LambdaQueryWrapper<ProductBomItem>()
                .in(ProductBomItem::getProductBomId, bomIds).eq(ProductBomItem::getDeletedFlag, 0)
                .orderByAsc(ProductBomItem::getLineNo, ProductBomItem::getProductBomItemId)))
                .forEach(value -> {
                    items.computeIfAbsent(value.getProductBomRouteId(), key -> new ArrayList<>()).add(value);
                    testItems.computeIfAbsent(value.getProductBomId(), key -> new ArrayList<>()).add(value);
                });
        }
        if (withProducts) {
            safe(productRepository.selectList(new LambdaQueryWrapper<Product>().eq(Product::getDeletedFlag, 0)
                .and(query -> query.in(Product::getProductId, ownerIds).or().in(Product::getParentProductId, ownerIds))
                .orderByAsc(Product::getProductId))).forEach(value -> {
                    products.put(value.getProductId(), value);
                    if (value.getParentProductId() != null)
                        children.computeIfAbsent(value.getParentProductId(), key -> new ArrayList<>()).add(value);
                });
        }
        return new BatchData(routes, colors, items, testItems, costs, products, children);
    }

    private ProductBomCostSnapshotVO toCostVo(ProductBomCostSnapshot value) {
        return ProductBomCostSnapshotVO.builder().materialCost(value.getMaterialCost()).lossCost(value.getLossCost())
            .processCost(value.getProcessCost()).packageCost(value.getPackageCost()).laborCost(value.getLaborCost())
            .toolingCost(value.getToolingCost()).otherCost(value.getOtherCost()).totalCost(value.getTotalCost())
            .currencyCode(value.getCurrencyCode()).calculatedAt(value.getCalculatedAt()).build();
    }

    private record BatchData(Map<Long, List<ProductBomRoute>> routes,
                             Map<Long, List<ProductBomRouteColor>> colors,
                             Map<Long, List<ProductBomItem>> items,
                             Map<Long, List<ProductBomItem>> testItems,
                             Map<Long, ProductBomCostSnapshotVO> costs,
                             Map<Long, Product> products,
                             Map<Long, List<Product>> children) {
        List<ProductBomRoute> routesFor(Long bomId) { return routes.getOrDefault(bomId, List.of()); }
        List<ProductBomRouteColor> colorsFor(Long routeId) { return colors.getOrDefault(routeId, List.of()); }
        List<ProductBomItem> itemsFor(Long routeId) { return items.getOrDefault(routeId, List.of()); }
    }

    private <T> List<T> safe(List<T> values) {
        return values == null ? List.of() : values;
    }
}
