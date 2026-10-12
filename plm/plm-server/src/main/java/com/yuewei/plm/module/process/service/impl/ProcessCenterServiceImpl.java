package com.yuewei.plm.module.process.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.module.bom.entity.ProductBomRoute;
import com.yuewei.plm.module.bom.entity.ProductBomRouteColor;
import com.yuewei.plm.module.bom.repository.ProductBomRouteColorRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteRepository;
import com.yuewei.plm.module.process.entity.ProcessEntity;
import com.yuewei.plm.module.process.repository.ProcessRepository;
import com.yuewei.plm.module.process.service.ProcessCenterService;
import com.yuewei.plm.module.process.vo.LinkedBomRouteVO;
import com.yuewei.plm.module.process.vo.ProcessCenterSnapshotVO;
import com.yuewei.plm.module.process.vo.ProcessMetricCardVO;
import com.yuewei.plm.module.process.vo.ProcessOperationRecordVO;
import com.yuewei.plm.module.process.vo.ProcessOperationVO;
import com.yuewei.plm.module.process.vo.ProcessRouteColorVO;
import com.yuewei.plm.module.process.vo.ProcessRouteDetailVO;
import com.yuewei.plm.module.process.vo.ProcessRouteListItemVO;
import com.yuewei.plm.module.process.vo.ProcessRouteRelationVO;
import com.yuewei.plm.module.process.vo.ProcessRouteSkuVO;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import java.math.BigDecimal;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.function.Function;
import java.util.stream.Collectors;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

@Service
@RequiredArgsConstructor
public class ProcessCenterServiceImpl implements ProcessCenterService {
    private static final String TYPE_ROUTING = "routing";
    private static final String TYPE_OPERATION = "operation";
    private static final DateTimeFormatter DATE_TIME = DateTimeFormatter.ISO_LOCAL_DATE_TIME;

    private final ProductRepository productRepository;
    private final ProcessRepository processRepository;
    private final ProductBomRouteRepository bomRouteRepository;
    private final ProductBomRouteColorRepository bomRouteColorRepository;
    private final ObjectMapper objectMapper;

    @Override
    public ProcessCenterSnapshotVO snapshot() {
        List<ProcessEntity> routes = safe(processRepository.selectList(new LambdaQueryWrapper<ProcessEntity>()
            .eq(ProcessEntity::getProcessType, TYPE_ROUTING)
            .eq(ProcessEntity::getDeletedFlag, 0)
            .orderByDesc(ProcessEntity::getProcessId)));
        if (routes.isEmpty()) {
            return ProcessCenterSnapshotVO.builder()
                .metrics(metrics(List.of()))
                .routes(List.of())
                .routeDetails(Map.of())
                .templates(List.of())
                .build();
        }

        Map<Long, Product> products = productsById(routes.stream().map(ProcessEntity::getProductId).toList());
        Map<Long, List<ProcessOperationVO>> operationsByRoute = operationsByRoute(routes.stream().map(ProcessEntity::getProcessId).toList());
        Map<Long, List<ProductBomRoute>> bomRoutesByProcess = bomRoutesByProcess(routes.stream().map(ProcessEntity::getProcessId).toList());
        Map<Long, List<ProcessRouteColorVO>> colorsByBomRoute = colorsByBomRoute(flatten(bomRoutesByProcess.values()).stream()
            .map(ProductBomRoute::getProductBomRouteId).toList());
        Map<Long, List<Product>> skusByProduct = skusByProduct(products.values());

        List<ProcessRouteListItemVO> rows = routes.stream()
            .map(route -> toListItem(route, products.get(route.getProductId()),
                operationsByRoute.getOrDefault(route.getProcessId(), List.of()),
                bomRoutesByProcess.getOrDefault(route.getProcessId(), List.of()),
                colorsByBomRoute,
                skusByProduct.getOrDefault(route.getProductId(), List.of())))
            .toList();
        Map<Long, ProcessRouteDetailVO> details = routes.stream().collect(Collectors.toMap(
            ProcessEntity::getProcessId,
            route -> toDetail(route, products.get(route.getProductId()),
                operationsByRoute.getOrDefault(route.getProcessId(), List.of())),
            (first, ignored) -> first,
            LinkedHashMap::new
        ));
        return ProcessCenterSnapshotVO.builder()
            .metrics(metrics(rows))
            .routes(rows)
            .routeDetails(details)
            .templates(List.of())
            .build();
    }

    @Override
    public ProcessRouteRelationVO relations(Long processId) {
        ProcessEntity route = requireRoute(processId);
        Product product = productRepository.selectById(route.getProductId());
        if (product == null || Integer.valueOf(1).equals(product.getDeletedFlag())) {
            throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "工艺路线所属产品不存在");
        }
        List<ProcessOperationVO> operations = listOperations(processId);
        List<ProductBomRoute> bomRoutes = activeBomRoutes(processId);
        Map<Long, List<ProcessRouteColorVO>> colorsByBomRoute = colorsByBomRoute(bomRoutes.stream()
            .map(ProductBomRoute::getProductBomRouteId).toList());
        List<ProcessRouteColorVO> colors = distinctColors(bomRoutes, colorsByBomRoute);
        List<ProcessRouteSkuVO> skus = routeSkus(product, bomRoutes, colorsByBomRoute, skuCandidates(product));
        return ProcessRouteRelationVO.builder()
            .processId(route.getProcessId())
            .processCode(route.getProcessCode())
            .processName(route.getProcessName())
            .productId(product.getProductId())
            .productCode(product.getProductCode())
            .productName(product.getProductName())
            .versionNo(route.getVersionNo())
            .status(route.getStatus())
            .colors(colors)
            .skus(skus)
            .operations(operations)
            .linkedBomRoutes(bomRoutes.stream().map(this::toLinkedBomRoute).toList())
            .build();
    }

    private ProcessRouteListItemVO toListItem(ProcessEntity route, Product product, List<ProcessOperationVO> operations,
                                              List<ProductBomRoute> bomRoutes,
                                              Map<Long, List<ProcessRouteColorVO>> colorsByBomRoute,
                                              List<Product> skuCandidates) {
        List<ProcessRouteColorVO> colors = distinctColors(bomRoutes, colorsByBomRoute);
        List<ProcessRouteSkuVO> skus = product == null ? List.of() : routeSkus(product, bomRoutes, colorsByBomRoute, skuCandidates);
        return ProcessRouteListItemVO.builder()
            .routeId(route.getProcessId())
            .processId(route.getProcessId())
            .routeCode(route.getProcessCode())
            .routeName(route.getProcessName())
            .productId(product == null ? route.getProductId() : product.getProductId())
            .productCode(product == null ? null : product.getProductCode())
            .productName(product == null ? null : product.getProductName())
            .model(product == null ? null : product.getModel())
            .versionNo(route.getVersionNo())
            .routeType(routeType(product))
            .status(route.getStatus())
            .templateSource(templateSource(route))
            .owner(firstNonBlank(route.getUpdatedBy(), route.getCreatedBy(), product == null ? null : product.getUpdatedBy()))
            .operationCount(operations.size())
            .colorCount(colors.size())
            .colors(colors)
            .skuCount(skus.size())
            .totalCost(BigDecimal.ZERO)
            .currentGate(currentGate(route))
            .riskLevel("low")
            .hasExternalOperation(false)
            .hasDifferenceOperation(false)
            .updatedAt(route.getUpdatedAt() == null ? null : DATE_TIME.format(route.getUpdatedAt()))
            .targetPath("/processes?routeId=" + route.getProcessId())
            .build();
    }

    private ProcessRouteDetailVO toDetail(ProcessEntity route, Product product, List<ProcessOperationVO> operations) {
        return ProcessRouteDetailVO.builder()
            .routeId(route.getProcessId())
            .processId(route.getProcessId())
            .routeCode(route.getProcessCode())
            .routeName(route.getProcessName())
            .productId(product == null ? route.getProductId() : product.getProductId())
            .productCode(product == null ? null : product.getProductCode())
            .productName(product == null ? null : product.getProductName())
            .versionNo(route.getVersionNo())
            .routeType(routeType(product))
            .status(route.getStatus())
            .templateSource(templateSource(route))
            .owner(firstNonBlank(route.getUpdatedBy(), route.getCreatedBy(), product == null ? null : product.getUpdatedBy()))
            .currentGate(currentGate(route))
            .totalCost(BigDecimal.ZERO)
            .passedGate("locked".equals(route.getStatus()) || "confirmed".equals(route.getStatus()))
            .isLocked("locked".equals(route.getStatus()))
            .differenceOperationCount(0)
            .inheritedFrom(null)
            .overviewNote("项目工艺路线来自真实 Process 数据，颜色和 SKU 在详情抽屉中按 BOM 路线聚合。")
            .operations(operations.stream().map(this::toOperationRecord).toList())
            .confirmations(List.of())
            .gateChecks(List.of())
            .attachments(List.of())
            .changes(List.of())
            .impacts(List.of())
            .build();
    }

    private ProcessOperationRecordVO toOperationRecord(ProcessOperationVO operation) {
        return ProcessOperationRecordVO.builder()
            .operationId(operation.getProcessId())
            .operationCode(firstNonBlank(operation.getBusinessOperationCode(), operation.getOperationCode(), operation.getProcessCode()))
            .sequenceNo(operation.getSequenceNo())
            .operationName(operation.getProcessName())
            .operationType(operation.getOperationCraftCode())
            .workstationName("--")
            .supplierName(null)
            .parameterSummary(operation.getProcessParamJson())
            .qualityRequirement(operation.getQualityRequirement())
            .unitCost(BigDecimal.ZERO)
            .leadDays(0)
            .attachmentStatus("missing")
            .isKeyProcess(Boolean.FALSE)
            .isExternalOperation(Boolean.FALSE)
            .isDifferenceOperation(Boolean.FALSE)
            .changedInCurrentVersion(Boolean.FALSE)
            .confirmerName(operation.getStatus())
            .confirmerRole("工艺状态")
            .build();
    }

    private List<ProcessMetricCardVO> metrics(List<ProcessRouteListItemVO> rows) {
        long locked = rows.stream().filter(row -> "locked".equals(row.getStatus())).count();
        long withSku = rows.stream().filter(row -> row.getSkuCount() != null && row.getSkuCount() > 0).count();
        return List.of(
            ProcessMetricCardVO.builder().label("项目工艺路线").value(rows.size()).hint("真实 Process 路线").build(),
            ProcessMetricCardVO.builder().label("已锁定路线").value(locked).hint("可进入投产确认").build(),
            ProcessMetricCardVO.builder().label("有关联 SKU").value(withSku).hint("已匹配颜色或 SKU").build()
        );
    }

    private ProcessEntity requireRoute(Long processId) {
        ProcessEntity route = processRepository.selectById(processId);
        if (route == null || Integer.valueOf(1).equals(route.getDeletedFlag()) || !TYPE_ROUTING.equals(route.getProcessType())) {
            throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "工艺路线不存在");
        }
        return route;
    }

    private Map<Long, Product> productsById(Collection<Long> productIds) {
        List<Long> ids = productIds.stream().filter(Objects::nonNull).distinct().toList();
        if (ids.isEmpty()) return Map.of();
        return safe(productRepository.selectBatchIds(ids)).stream()
            .filter(product -> !Integer.valueOf(1).equals(product.getDeletedFlag()))
            .collect(Collectors.toMap(Product::getProductId, Function.identity(), (first, ignored) -> first));
    }

    private Map<Long, List<ProcessOperationVO>> operationsByRoute(Collection<Long> routeIds) {
        List<Long> ids = routeIds.stream().filter(Objects::nonNull).distinct().toList();
        if (ids.isEmpty()) return Map.of();
        return safe(processRepository.selectList(new LambdaQueryWrapper<ProcessEntity>()
            .in(ProcessEntity::getParentProcessId, ids)
            .eq(ProcessEntity::getProcessType, TYPE_OPERATION)
            .eq(ProcessEntity::getDeletedFlag, 0)
            .orderByAsc(ProcessEntity::getSequenceNo))).stream()
            .map(ProcessOperationVO::from)
            .collect(Collectors.groupingBy(ProcessOperationVO::getParentProcessId, LinkedHashMap::new, Collectors.toList()));
    }

    private List<ProcessOperationVO> listOperations(Long processId) {
        return safe(processRepository.selectList(new LambdaQueryWrapper<ProcessEntity>()
            .eq(ProcessEntity::getParentProcessId, processId)
            .eq(ProcessEntity::getProcessType, TYPE_OPERATION)
            .eq(ProcessEntity::getDeletedFlag, 0)
            .orderByAsc(ProcessEntity::getSequenceNo))).stream()
            .map(ProcessOperationVO::from)
            .toList();
    }

    private Map<Long, List<ProductBomRoute>> bomRoutesByProcess(Collection<Long> processIds) {
        List<Long> ids = processIds.stream().filter(Objects::nonNull).distinct().toList();
        if (ids.isEmpty()) return Map.of();
        return safe(bomRouteRepository.selectList(new LambdaQueryWrapper<ProductBomRoute>()
            .in(ProductBomRoute::getProcessId, ids)
            .eq(ProductBomRoute::getStatus, "active")
            .eq(ProductBomRoute::getDeletedFlag, 0))).stream()
            .collect(Collectors.groupingBy(ProductBomRoute::getProcessId, LinkedHashMap::new, Collectors.toList()));
    }

    private List<ProductBomRoute> activeBomRoutes(Long processId) {
        return safe(bomRouteRepository.selectList(new LambdaQueryWrapper<ProductBomRoute>()
            .eq(ProductBomRoute::getProcessId, processId)
            .eq(ProductBomRoute::getStatus, "active")
            .eq(ProductBomRoute::getDeletedFlag, 0)));
    }

    private Map<Long, List<ProcessRouteColorVO>> colorsByBomRoute(Collection<Long> productBomRouteIds) {
        List<Long> ids = productBomRouteIds.stream().filter(Objects::nonNull).distinct().toList();
        if (ids.isEmpty()) return Map.of();
        return safe(bomRouteColorRepository.selectList(new LambdaQueryWrapper<ProductBomRouteColor>()
            .in(ProductBomRouteColor::getProductBomRouteId, ids)
            .eq(ProductBomRouteColor::getStatus, "active")
            .eq(ProductBomRouteColor::getDeletedFlag, 0))).stream()
            .collect(Collectors.groupingBy(ProductBomRouteColor::getProductBomRouteId, LinkedHashMap::new,
                Collectors.mapping(color -> ProcessRouteColorVO.builder()
                    .codeItemId(color.getCodeItemId())
                    .colorCode(color.getColorCode())
                    .colorName(color.getColorName())
                    .build(), Collectors.toList())));
    }

    private Map<Long, List<Product>> skusByProduct(Collection<Product> products) {
        List<Long> productIds = products.stream().map(Product::getProductId).filter(Objects::nonNull).distinct().toList();
        if (productIds.isEmpty()) return Map.of();
        Map<Long, List<Product>> values = new HashMap<>();
        for (Product child : safe(productRepository.selectList(new LambdaQueryWrapper<Product>()
            .in(Product::getParentProductId, productIds)
            .eq(Product::getDeletedFlag, 0)))) {
            values.computeIfAbsent(child.getParentProductId(), ignored -> new ArrayList<>()).add(child);
        }
        for (Product product : products) {
            if ("model_variant".equals(product.getProductType()) && StringUtils.hasText(product.getColor())) {
                values.computeIfAbsent(product.getProductId(), ignored -> new ArrayList<>()).add(product);
            }
        }
        return values;
    }

    private List<Product> skuCandidates(Product product) {
        List<Product> values = new ArrayList<>(safe(productRepository.selectList(new LambdaQueryWrapper<Product>()
            .eq(Product::getParentProductId, product.getProductId())
            .eq(Product::getDeletedFlag, 0))));
        if ("model_variant".equals(product.getProductType()) && StringUtils.hasText(product.getColor())) {
            values.add(product);
        }
        return values;
    }

    private List<ProcessRouteSkuVO> routeSkus(Product product, List<ProductBomRoute> bomRoutes,
                                              Map<Long, List<ProcessRouteColorVO>> colorsByBomRoute,
                                              List<Product> skuCandidates) {
        if (bomRoutes.isEmpty()) return List.of();
        List<ProcessRouteSkuVO> result = new ArrayList<>();
        for (Product sku : skuCandidates) {
            ProductBomRoute matchedRoute = matchedRouteForColor(sku.getColorCode(), sku.getColor(), bomRoutes, colorsByBomRoute);
            if (matchedRoute == null) continue;
            result.add(ProcessRouteSkuVO.builder()
                .productId(sku.getProductId())
                .skuCode(skuDisplayCode(sku))
                .productName(sku.getProductName())
                .phoneModel(sku.getModel())
                .phoneModelCode(sku.getPhoneModelCode())
                .color(sku.getColor())
                .colorCode(sku.getColorCode())
                .finishedProductCode(sku.getFinishedProductCode())
                .status(sku.getStatus())
                .productBomRouteId(matchedRoute.getProductBomRouteId())
                .routeCode(matchedRoute.getRouteCode())
                .routeName(matchedRoute.getRouteName())
                .build());
        }
        if (result.isEmpty() && "model_variant".equals(product.getProductType()) && StringUtils.hasText(product.getColor())) {
            ProductBomRoute matchedRoute = matchedRouteForColor(product.getColorCode(), product.getColor(), bomRoutes, colorsByBomRoute);
            if (matchedRoute != null) {
                result.add(ProcessRouteSkuVO.builder()
                    .productId(product.getProductId())
                    .skuCode(skuDisplayCode(product))
                    .productName(product.getProductName())
                    .phoneModel(product.getModel())
                    .phoneModelCode(product.getPhoneModelCode())
                    .color(product.getColor())
                    .colorCode(product.getColorCode())
                    .finishedProductCode(product.getFinishedProductCode())
                    .status(product.getStatus())
                    .productBomRouteId(matchedRoute.getProductBomRouteId())
                    .routeCode(matchedRoute.getRouteCode())
                    .routeName(matchedRoute.getRouteName())
                    .build());
            }
        }
        return result;
    }

    private String skuDisplayCode(Product product) {
        return StringUtils.hasText(product.getFinishedProductCode()) ? product.getFinishedProductCode() : product.getProductCode();
    }

    private ProductBomRoute matchedRouteForColor(String colorCode, String colorName, List<ProductBomRoute> bomRoutes,
                                                 Map<Long, List<ProcessRouteColorVO>> colorsByBomRoute) {
        String normalizedCode = normalize(colorCode);
        if (normalizedCode != null) {
            return bomRoutes.stream()
                .filter(route -> colorsByBomRoute.getOrDefault(route.getProductBomRouteId(), List.of()).stream()
                    .anyMatch(color -> normalizedCode.equals(normalize(color.getColorCode()))))
                .findFirst()
                .orElse(null);
        }
        String normalizedName = normalize(colorName);
        if (normalizedName == null) return null;
        return bomRoutes.stream()
            .filter(route -> colorsByBomRoute.getOrDefault(route.getProductBomRouteId(), List.of()).stream()
                .anyMatch(color -> normalizedName.equals(normalize(color.getColorName()))))
            .findFirst()
            .orElse(null);
    }

    private List<ProcessRouteColorVO> distinctColors(List<ProductBomRoute> bomRoutes,
                                                     Map<Long, List<ProcessRouteColorVO>> colorsByBomRoute) {
        Map<String, ProcessRouteColorVO> values = new LinkedHashMap<>();
        for (ProductBomRoute route : bomRoutes) {
            for (ProcessRouteColorVO color : colorsByBomRoute.getOrDefault(route.getProductBomRouteId(), List.of())) {
                String key = firstNonBlank(color.getColorCode(), color.getColorName(), String.valueOf(color.getCodeItemId()));
                values.putIfAbsent(key, color);
            }
        }
        return new ArrayList<>(values.values());
    }

    private LinkedBomRouteVO toLinkedBomRoute(ProductBomRoute route) {
        return LinkedBomRouteVO.builder()
            .productBomRouteId(route.getProductBomRouteId())
            .productBomId(route.getProductBomId())
            .routeCode(route.getRouteCode())
            .routeName(route.getRouteName())
            .status(route.getStatus())
            .build();
    }

    private String routeType(Product product) {
        return product != null && "model_variant".equals(product.getProductType()) ? "new_model_variant" : "new_product_line";
    }

    private String currentGate(ProcessEntity route) {
        if ("locked".equals(route.getStatus())) return "已锁定";
        if ("confirmed".equals(route.getStatus())) return "已确认";
        return "工艺维护";
    }

    private String templateSource(ProcessEntity route) {
        String templateCode = jsonText(route.getProcessParamJson(), "routeTemplateCode");
        if (StringUtils.hasText(jsonText(route.getProcessParamJson(), "sourceProductCode"))) return "inherited";
        return StringUtils.hasText(templateCode) ? "standard" : "manual";
    }

    private String jsonText(String json, String field) {
        if (!StringUtils.hasText(json)) return null;
        try {
            JsonNode value = objectMapper.readTree(json).get(field);
            return value == null || value.isNull() ? null : value.asText();
        } catch (Exception ignored) {
            return null;
        }
    }

    private String firstNonBlank(String... values) {
        for (String value : values) {
            if (StringUtils.hasText(value)) return value.trim();
        }
        return null;
    }

    private String normalize(String value) {
        return StringUtils.hasText(value) ? value.trim().toLowerCase(Locale.ROOT) : null;
    }

    private <T> List<T> safe(List<T> values) {
        return values == null ? List.of() : values;
    }

    private <T> List<T> flatten(Collection<List<T>> values) {
        return values.stream().flatMap(Collection::stream).toList();
    }
}
