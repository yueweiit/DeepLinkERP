package com.yuewei.plm.module.bom.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.util.ProductBusinessCodeGenerator;
import com.yuewei.plm.module.bom.dto.ProductionColorConfirmDTO;
import com.yuewei.plm.module.bom.dto.ProductionOperationConfirmDTO;
import com.yuewei.plm.module.bom.dto.ProductionRouteConfirmDTO;
import com.yuewei.plm.module.bom.entity.ProcessProductionOperationSelection;
import com.yuewei.plm.module.bom.entity.ProductBom;
import com.yuewei.plm.module.bom.entity.ProductBomRoute;
import com.yuewei.plm.module.bom.entity.ProductBomRouteColor;
import com.yuewei.plm.module.bom.entity.ProductBomCostSnapshot;
import com.yuewei.plm.module.bom.entity.ProductBomRouteFormalSelection;
import com.yuewei.plm.module.bom.entity.ProductProductionColorDecision;
import com.yuewei.plm.module.bom.repository.ProcessProductionOperationSelectionRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteColorRepository;
import com.yuewei.plm.module.bom.repository.ProductBomCostSnapshotRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteFormalSelectionRepository;
import com.yuewei.plm.module.bom.repository.ProductProductionColorDecisionRepository;
import com.yuewei.plm.module.bom.vo.ProductionConfirmationVO;
import com.yuewei.plm.module.process.entity.ProcessEntity;
import com.yuewei.plm.module.process.repository.ProcessRepository;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import com.yuewei.plm.module.code.entity.CodeItem;
import com.yuewei.plm.module.code.service.CodeItemService;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

@Service
@RequiredArgsConstructor
public class ProductionConfirmationService {
    private final ProductRepository productRepository;
    private final ProductBomRepository bomRepository;
    private final ProductBomRouteRepository routeRepository;
    private final ProcessRepository processRepository;
    private final ProductBomRouteColorRepository routeColorRepository;
    private final ProductBomCostSnapshotRepository costRepository;
    private final ProductBomRouteFormalSelectionRepository formalSelectionRepository;
    private final ProcessProductionOperationSelectionRepository operationRepository;
    private final ProductProductionColorDecisionRepository colorRepository;
    private final CodeItemService codeItemService;
    private final ProductBusinessCodeGenerator businessCodeGenerator;

    @Transactional
    public ProductionConfirmationVO confirmOperations(Long projectId, ProductionOperationConfirmDTO dto) {
        ProductBomRoute route = routeRepository.selectById(dto.getProductBomRouteId());
        if (route == null) {
            throw validation("工艺路线不属于当前项目或已失效");
        }
        ProductionRouteConfirmDTO.RouteSelection selection = new ProductionRouteConfirmDTO.RouteSelection();
        selection.setProcessId(route.getProcessId());
        selection.setProductBomId(route.getProductBomId());
        selection.setProductBomRouteId(route.getProductBomRouteId());
        selection.setOperationProcessIds(dto.getOperationProcessIds());
        selection.setApplicableColors(routeApplicableColors(route));
        ProductionRouteConfirmDTO command = new ProductionRouteConfirmDTO();
        command.setRoutes(List.of(selection));
        return confirmRoutes(projectId, command);
    }

    @Transactional
    public ProductionConfirmationVO confirmRoutes(Long projectId, ProductionRouteConfirmDTO dto) {
        Product project = requireProject(projectId);
        if (dto.getRoutes() == null || dto.getRoutes().isEmpty()) {
            throw validation("请至少选择一条工艺路线");
        }
        Set<Long> processIds = new HashSet<>();
        Set<Long> routeIds = new HashSet<>();
        List<ConfirmedRoute> confirmedRoutes = new ArrayList<>();
        String batchNo = UUID.randomUUID().toString();
        LocalDateTime now = LocalDateTime.now();
        for (ProductionRouteConfirmDTO.RouteSelection selection : dto.getRoutes()) {
            if (selection.getOperationProcessIds() == null || selection.getOperationProcessIds().isEmpty()) {
                throw validation("请至少选择一道投产工序");
            }
            if (!routeIds.add(selection.getProductBomRouteId())) {
                throw validation("同一 BOM 工艺路线不能重复选择");
            }
            ProductBom bom = requireConfirmableBom(projectId, selection.getProductBomId());
            ProductBomRoute route = requireConfirmableBomRoute(projectId, bom, selection);
            List<ProcessEntity> operations = requireRouteOperations(route, selection.getOperationProcessIds());
            requireRouteCost(bom, route);
            List<ProductionRouteConfirmDTO.ApplicableColor> applicableColors =
                requireApplicableColors(route, selection.getApplicableColors());
            processIds.add(route.getProcessId());
            confirmedRoutes.add(new ConfirmedRoute(bom, route, operations, applicableColors));
        }
        for (Long processId : processIds) {
            archiveFormalSelections(projectId, processId, dto.getRemark());
            archiveOperationsByProcess(projectId, processId);
            archiveColorsByProcess(projectId, processId);
        }
        for (ConfirmedRoute confirmedRoute : confirmedRoutes) {
            ProductBom bom = confirmedRoute.bom();
            ProductBomRoute route = confirmedRoute.route();
            ProductBomRouteFormalSelection formal = new ProductBomRouteFormalSelection();
            formal.setProductId(projectId);
            formal.setProductBomId(bom.getProductBomId());
            formal.setProductBomRouteId(route.getProductBomRouteId());
            formal.setProcessId(route.getProcessId());
            formal.setBomVersionNo(bom.getVersionNo());
            formal.setSelectionBatchNo(batchNo);
            formal.setStatus("active");
            formal.setConfirmedAt(now);
            formal.setConfirmedBy("system");
            formal.setRemark(dto.getRemark());
            fillCreate(formal, now);
            formalSelectionRepository.insert(formal);
            if (!"formal".equals(bom.getBomScope())) {
                bom.setBomScope("formal");
                bom.setUpdatedAt(now);
                bom.setUpdatedBy("system");
                bomRepository.updateById(bom);
            }
            ProcessEntity routeProcess = processRepository.selectById(route.getProcessId());
            String routeVersionNo = routeProcess == null ? null : routeProcess.getVersionNo();
            for (ProcessEntity operation : confirmedRoute.operations()) {
                ProcessProductionOperationSelection value = new ProcessProductionOperationSelection();
                value.setProductId(projectId);
                value.setProductBomRouteId(route.getProductBomRouteId());
                value.setProcessId(route.getProcessId());
                value.setOperationProcessId(operation.getProcessId());
                value.setRouteVersionNo(routeVersionNo);
                value.setSelectionBatchNo(batchNo);
                value.setStatus("confirmed");
                value.setConfirmedAt(now);
                value.setConfirmedBy("system");
                fillCreate(value, now);
                operationRepository.insert(value);
            }
            for (ProductionRouteConfirmDTO.ApplicableColor color : confirmedRoute.applicableColors()) {
                ProductProductionColorDecision decision = new ProductProductionColorDecision();
                decision.setProductId(projectId);
                decision.setCodeItemId(color.getCodeItemId());
                decision.setColorCode(color.getColorCode());
                decision.setColorName(color.getColorName().trim());
                decision.setProductBomId(bom.getProductBomId());
                decision.setProductBomRouteId(route.getProductBomRouteId());
                decision.setDecisionBatchNo(batchNo);
                decision.setSelectedFlag(1);
                decision.setStatus("confirmed");
                decision.setConfirmedAt(now);
                decision.setConfirmedBy("system");
                fillCreate(decision, now);
                colorRepository.insert(decision);
            }
        }
        return get(project.getProductId());
    }

    private record ConfirmedRoute(ProductBom bom,
                                  ProductBomRoute route,
                                  List<ProcessEntity> operations,
                                  List<ProductionRouteConfirmDTO.ApplicableColor> applicableColors) {
    }

    @Transactional
    public ProductionConfirmationVO confirmColors(Long projectId, ProductionColorConfirmDTO dto) {
        Product project = requireProject(projectId);
        if (dto.getColors() == null || dto.getColors().isEmpty()) {
            throw validation("请至少选择一个批量投产颜色");
        }
        List<ProductionColorConfirmDTO.ColorSelection> colors = dto.getColors().stream()
            .filter(value -> value.getColorName() != null && !value.getColorName().isBlank())
            .collect(java.util.stream.Collectors.toMap(
                value -> value.getColorName().trim().toLowerCase(Locale.ROOT),
                value -> value,
                (first, ignored) -> first,
                java.util.LinkedHashMap::new
            )).values().stream().toList();
        for (ProductionColorConfirmDTO.ColorSelection color : colors) {
            codeItemService.requireEnabledColor(color.getCodeItemId(), color.getColorCode());
            requireColorRoute(projectId, color);
        }
        archiveColors(projectId);
        String batchNo = UUID.randomUUID().toString();
        LocalDateTime now = LocalDateTime.now();
        for (ProductionColorConfirmDTO.ColorSelection color : colors) {
            ProductProductionColorDecision decision = new ProductProductionColorDecision();
            decision.setProductId(projectId);
            decision.setCodeItemId(color.getCodeItemId());
            decision.setColorCode(color.getColorCode());
            decision.setColorName(color.getColorName().trim());
            decision.setProductBomId(color.getProductBomId());
            decision.setProductBomRouteId(color.getProductBomRouteId());
            decision.setDecisionBatchNo(batchNo);
            decision.setSelectedFlag(1);
            decision.setStatus("confirmed");
            decision.setConfirmedAt(now);
            decision.setConfirmedBy("system");
            fillCreate(decision, now);
            colorRepository.insert(decision);
        }
        int createdSkuCount = syncModelVariantConfirmedColorsAndSkus(project);
        ProductionConfirmationVO result = get(projectId);
        result.setSelectedColorCount(colors.size());
        result.setColors(colors.stream().map(value -> value.getColorName().trim()).toList());
        result.setCreatedSkuCount(createdSkuCount);
        return result;
    }

    @Transactional
    public int syncModelVariantConfirmedColorsAndSkus(Product project) {
        if (project == null || !"model_variant".equals(project.getProductType())) {
            return 0;
        }
        List<ProductProductionColorDecision> decisions = confirmedColorDecisions(project.getProductId());
        if (decisions.isEmpty()) {
            return 0;
        }
        LocalDateTime now = LocalDateTime.now();
        int createdSkuCount = 0;
        for (ProductProductionColorDecision decision : decisions) {
            Product sku = findSku(project, decision);
            if (sku == null) {
                sku = createSku(project, decision, now);
                productRepository.insert(sku);
                createdSkuCount++;
            } else if (applySkuFields(sku, project, decision, now)) {
                productRepository.updateById(sku);
            }
            if (sku.getProductId() != null && !Objects.equals(decision.getCreatedSkuProductId(), sku.getProductId())) {
                decision.setCreatedSkuProductId(sku.getProductId());
                decision.setUpdatedAt(now);
                decision.setUpdatedBy("system");
                colorRepository.updateById(decision);
            }
        }
        if (applyProjectColor(project, decisions, now)) {
            productRepository.updateById(project);
        }
        return createdSkuCount;
    }

    public ProductionConfirmationVO get(Long projectId) {
        requireProject(projectId);
        List<ProcessProductionOperationSelection> operations = safe(operationRepository.selectList(
            new LambdaQueryWrapper<ProcessProductionOperationSelection>()
                .eq(ProcessProductionOperationSelection::getProductId, projectId)
                .eq(ProcessProductionOperationSelection::getStatus, "confirmed")
                .eq(ProcessProductionOperationSelection::getDeletedFlag, 0)));
        List<ProductProductionColorDecision> colors = safe(colorRepository.selectList(
            new LambdaQueryWrapper<ProductProductionColorDecision>()
                .eq(ProductProductionColorDecision::getProductId, projectId)
                .eq(ProductProductionColorDecision::getStatus, "confirmed")
                .eq(ProductProductionColorDecision::getDeletedFlag, 0)));
        Map<Long, List<Long>> operationIdsByRoute = operations.stream()
            .filter(selection -> selection.getProductBomRouteId() != null)
            .collect(Collectors.groupingBy(ProcessProductionOperationSelection::getProductBomRouteId,
                Collectors.mapping(ProcessProductionOperationSelection::getOperationProcessId, Collectors.toList())));
        Map<Long, List<ProductionConfirmationVO.ApplicableColorVO>> colorsByRoute = colors.stream()
            .filter(color -> color.getProductBomRouteId() != null)
            .collect(Collectors.groupingBy(ProductProductionColorDecision::getProductBomRouteId,
                Collectors.mapping(this::toApplicableColorVO, Collectors.toList())));
        List<ProductionConfirmationVO.RouteSelectionVO> routeSelections = activeFormalSelections(projectId).stream()
            .map(selection -> {
                ProductBomRoute route = routeRepository.selectById(selection.getProductBomRouteId());
                return ProductionConfirmationVO.RouteSelectionVO.builder()
                    .processId(selection.getProcessId())
                    .productBomId(selection.getProductBomId())
                    .productBomRouteId(selection.getProductBomRouteId())
                    .routeName(route == null ? null : route.getRouteName())
                    .bomVersionNo(selection.getBomVersionNo())
                    .operationProcessIds(operationIdsByRoute.getOrDefault(selection.getProductBomRouteId(), List.of()))
                    .applicableColors(colorsByRoute.getOrDefault(selection.getProductBomRouteId(), List.of()))
                    .build();
            }).toList();
        return ProductionConfirmationVO.builder().productId(projectId)
            .selectedOperationCount(operations.size()).selectedColorCount(colors.size()).createdSkuCount(0)
            .operationProcessIds(operations.stream().map(ProcessProductionOperationSelection::getOperationProcessId).toList())
            .routeSelections(routeSelections)
            .colors(colors.stream()
                .map(color -> firstNonBlank(color.getColorName(), color.getColorCode()))
                .filter(Objects::nonNull)
                .toList()).build();
    }

    public void requireOperationsConfirmed(Long projectId) {
        requireProject(projectId);
        List<ProductBomRouteFormalSelection> selections = activeFormalSelections(projectId);
        if (selections.isEmpty()) {
            throw new BusinessException(ErrorCodeConstants.STATUS_TRANSITION_ILLEGAL, "没有可确认的有效 BOM 路线");
        }
        boolean hasValidSelection = false;
        for (ProductBomRouteFormalSelection selection : selections) {
            ProductBomRoute route = routeRepository.selectById(selection.getProductBomRouteId());
            if (!isActiveProjectRoute(projectId, route)) {
                invalidateStaleFormalSelection(selection, "已确认路线关联的 BOM 路线已失效");
                continue;
            }
            hasValidSelection = true;
            if (!hasConfirmedOperation(projectId, route)) {
                throw new BusinessException(ErrorCodeConstants.STATUS_TRANSITION_ILLEGAL,
                    "路线 " + route.getRouteName() + " 尚未确认有效投产工序");
            }
        }
        if (!hasValidSelection) {
            throw new BusinessException(ErrorCodeConstants.STATUS_TRANSITION_ILLEGAL, "没有可确认的有效 BOM 路线");
        }
    }

    public void requireBomRoutesDetermined(Long projectId) {
        requireProject(projectId);
        List<ProductBom> boms = activeProjectBoms(projectId);
        boolean ready = boms.stream().anyMatch(bom -> !safe(routeRepository.selectList(
            new LambdaQueryWrapper<ProductBomRoute>()
                .eq(ProductBomRoute::getProductBomId, bom.getProductBomId())
                .eq(ProductBomRoute::getStatus, "active").eq(ProductBomRoute::getDeletedFlag, 0))).isEmpty());
        if (!ready) {
            throw new BusinessException(ErrorCodeConstants.STATUS_TRANSITION_ILLEGAL,
                "BOM 与工艺路线尚未定版，不能推进到敲定工序");
        }
    }

    public void requireColorsConfirmed(Long projectId) {
        if (get(projectId).getSelectedColorCount() < 1) {
            throw new BusinessException(ErrorCodeConstants.STATUS_TRANSITION_ILLEGAL, "正式投产颜色尚未确认，不能完成发布");
        }
    }

    private ProductBom requireConfirmableBom(Long projectId, Long productBomId) {
        ProductBom bom = bomRepository.selectById(productBomId);
        if (bom == null || !projectId.equals(bom.getProductId()) || Integer.valueOf(1).equals(bom.getDeletedFlag())) {
            throw validation("正式 BOM 必须属于当前项目");
        }
        if (!"released".equals(bom.getStatus())) {
            throw validation("使用 BOM 必须是当前项目已定版 BOM");
        }
        return bom;
    }

    private ProductBomRoute requireConfirmableBomRoute(Long projectId, ProductBom bom,
                                                       ProductionRouteConfirmDTO.RouteSelection selection) {
        ProductBomRoute route = routeRepository.selectById(selection.getProductBomRouteId());
        if (route == null || Integer.valueOf(1).equals(route.getDeletedFlag()) || !"active".equals(route.getStatus())) {
            throw validation("正式 BOM 路线无效");
        }
        if (!projectId.equals(route.getProductId()) || !bom.getProductBomId().equals(route.getProductBomId())) {
            throw validation("正式 BOM 路线不属于当前项目或当前 BOM");
        }
        if (!selection.getProcessId().equals(route.getProcessId())) {
            throw validation("正式 BOM 路线与工艺路线不一致");
        }
        return route;
    }

    private List<ProcessEntity> requireRouteOperations(ProductBomRoute route, List<Long> operationProcessIds) {
        return operationProcessIds.stream().filter(Objects::nonNull).distinct().map(operationId -> {
            ProcessEntity operation = processRepository.selectById(operationId);
            if (operation == null || !route.getProcessId().equals(operation.getParentProcessId())
                || Integer.valueOf(1).equals(operation.getDeletedFlag())) {
                throw validation("所选工序不属于当前工艺路线");
            }
            return operation;
        }).sorted(Comparator.comparing(
            ProcessEntity::getSequenceNo,
            Comparator.nullsLast(Comparator.naturalOrder())
        ).thenComparing(ProcessEntity::getProcessId)).toList();
    }

    private void requireRouteCost(ProductBom bom, ProductBomRoute route) {
        boolean hasCost = !safe(costRepository.selectList(new LambdaQueryWrapper<ProductBomCostSnapshot>()
            .eq(ProductBomCostSnapshot::getProductBomId, bom.getProductBomId())
            .eq(ProductBomCostSnapshot::getProductBomRouteId, route.getProductBomRouteId())
            .in(ProductBomCostSnapshot::getStatus, List.of("current", "baseline"))
            .eq(ProductBomCostSnapshot::getDeletedFlag, 0))).isEmpty();
        if (!hasCost) {
            throw validation("路线 " + route.getRouteName() + " 尚未完成成本计算");
        }
    }

    private List<ProductionRouteConfirmDTO.ApplicableColor> requireApplicableColors(
        ProductBomRoute route,
        List<ProductionRouteConfirmDTO.ApplicableColor> requested
    ) {
        List<ProductionRouteConfirmDTO.ApplicableColor> source =
            requested == null || requested.isEmpty() ? routeApplicableColors(route) : requested;
        if (source.isEmpty()) {
            throw validation("请至少选择一个适用颜色");
        }
        Map<String, ProductionRouteConfirmDTO.ApplicableColor> values = new LinkedHashMap<>();
        for (ProductionRouteConfirmDTO.ApplicableColor color : source) {
            if (color == null || color.getCodeItemId() == null) {
                throw validation("适用颜色不能为空");
            }
            CodeItem codeItem = codeItemService.requireEnabledColor(color.getCodeItemId(), color.getColorCode());
            String colorCode = firstNonBlank(color.getColorCode(), codeItem == null ? null : codeItem.getCodeValue());
            String colorName = firstNonBlank(color.getColorName(), codeItem == null ? null : codeItem.getCodeName());
            if (colorCode == null || colorName == null) {
                throw validation("适用颜色信息不完整");
            }
            boolean belongsToRoute = !safe(routeColorRepository.selectList(new LambdaQueryWrapper<ProductBomRouteColor>()
                .eq(ProductBomRouteColor::getProductBomRouteId, route.getProductBomRouteId())
                .eq(ProductBomRouteColor::getCodeItemId, color.getCodeItemId())
                .eq(ProductBomRouteColor::getColorCode, colorCode)
                .eq(ProductBomRouteColor::getStatus, "active")
                .eq(ProductBomRouteColor::getDeletedFlag, 0))).isEmpty();
            if (!belongsToRoute) {
                throw validation("适用颜色不属于所选使用 BOM");
            }
            ProductionRouteConfirmDTO.ApplicableColor normalized = new ProductionRouteConfirmDTO.ApplicableColor();
            normalized.setCodeItemId(color.getCodeItemId());
            normalized.setColorCode(colorCode);
            normalized.setColorName(colorName);
            values.put(color.getCodeItemId() + "|" + colorCode, normalized);
        }
        return new ArrayList<>(values.values());
    }

    private List<ProductionRouteConfirmDTO.ApplicableColor> routeApplicableColors(ProductBomRoute route) {
        return safe(routeColorRepository.selectList(new LambdaQueryWrapper<ProductBomRouteColor>()
            .eq(ProductBomRouteColor::getProductBomRouteId, route.getProductBomRouteId())
            .eq(ProductBomRouteColor::getStatus, "active")
            .eq(ProductBomRouteColor::getDeletedFlag, 0))).stream().map(color -> {
                ProductionRouteConfirmDTO.ApplicableColor value = new ProductionRouteConfirmDTO.ApplicableColor();
                value.setCodeItemId(color.getCodeItemId());
                value.setColorCode(color.getColorCode());
                value.setColorName(color.getColorName());
                return value;
            }).toList();
    }

    private String firstNonBlank(String first, String second) {
        if (first != null && !first.isBlank()) return first.trim();
        if (second != null && !second.isBlank()) return second.trim();
        return null;
    }

    private boolean isActiveProjectRoute(Long projectId, ProductBomRoute route) {
        return route != null
            && "active".equals(route.getStatus())
            && !Integer.valueOf(1).equals(route.getDeletedFlag())
            && (route.getProductId() == null || projectId.equals(route.getProductId()));
    }

    private void invalidateStaleFormalSelection(ProductBomRouteFormalSelection selection, String reason) {
        LocalDateTime now = LocalDateTime.now();
        selection.setStatus("invalidated");
        selection.setInvalidatedAt(now);
        selection.setInvalidatedReason(reason);
        selection.setUpdatedAt(now);
        selection.setUpdatedBy("system");
        formalSelectionRepository.updateById(selection);
    }

    private void archiveFormalSelections(Long projectId, Long processId, String reason) {
        LocalDateTime now = LocalDateTime.now();
        for (ProductBomRouteFormalSelection selection : activeFormalSelections(projectId, processId)) {
            selection.setStatus("invalidated");
            selection.setInvalidatedAt(now);
            selection.setInvalidatedReason(reason == null || reason.isBlank() ? "重新敲定使用 BOM 范围" : reason);
            selection.setUpdatedAt(now);
            selection.setUpdatedBy("system");
            formalSelectionRepository.updateById(selection);
        }
    }

    private void archiveOperationsByProcess(Long projectId, Long processId) {
        LocalDateTime now = LocalDateTime.now();
        for (ProcessProductionOperationSelection value : safe(operationRepository.selectList(
            new LambdaQueryWrapper<ProcessProductionOperationSelection>()
                .eq(ProcessProductionOperationSelection::getProductId, projectId)
                .eq(ProcessProductionOperationSelection::getProcessId, processId)
                .eq(ProcessProductionOperationSelection::getDeletedFlag, 0)))) {
            value.setStatus("archived");
            value.setDeletedFlag(1);
            value.setUpdatedAt(now);
            value.setUpdatedBy("system");
            operationRepository.updateById(value);
        }
    }

    private void archiveColorsByProcess(Long projectId, Long processId) {
        LocalDateTime now = LocalDateTime.now();
        for (ProductProductionColorDecision value : safe(colorRepository.selectList(
            new LambdaQueryWrapper<ProductProductionColorDecision>()
                .eq(ProductProductionColorDecision::getProductId, projectId)
                .eq(ProductProductionColorDecision::getDeletedFlag, 0)))) {
            ProductBomRoute route = value.getProductBomRouteId() == null ? null : routeRepository.selectById(value.getProductBomRouteId());
            if (route == null || !processId.equals(route.getProcessId())) continue;
            value.setStatus("archived");
            value.setDeletedFlag(1);
            value.setUpdatedAt(now);
            value.setUpdatedBy("system");
            colorRepository.updateById(value);
        }
    }

    private boolean hasActiveFormalSelection(Long projectId, Long bomId, Long routeId, Long processId) {
        return activeFormalSelections(projectId, processId).stream()
            .anyMatch(selection -> bomId.equals(selection.getProductBomId())
                && routeId.equals(selection.getProductBomRouteId()));
    }

    private void requireColorRoute(Long projectId, ProductionColorConfirmDTO.ColorSelection color) {
        ProductBom bom = bomRepository.selectById(color.getProductBomId());
        ProductBomRoute route = routeRepository.selectById(color.getProductBomRouteId());
        if (bom == null || !projectId.equals(bom.getProductId())
            || !"released".equals(bom.getStatus())) {
            throw validation("投产颜色必须关联当前项目已定版 BOM");
        }
        if (route == null || !bom.getProductBomId().equals(route.getProductBomId()) || !"active".equals(route.getStatus())) {
            throw validation("投产颜色关联的工艺路线无效");
        }
        if (!hasActiveFormalSelection(projectId, bom.getProductBomId(), route.getProductBomRouteId(), route.getProcessId())) {
            throw validation("投产颜色必须引用已确认的使用 BOM 路线");
        }
        boolean belongsToRoute = !safe(routeColorRepository.selectList(new LambdaQueryWrapper<ProductBomRouteColor>()
            .eq(ProductBomRouteColor::getProductBomRouteId, route.getProductBomRouteId())
            .eq(ProductBomRouteColor::getCodeItemId, color.getCodeItemId())
            .eq(ProductBomRouteColor::getColorCode, color.getColorCode())
            .eq(ProductBomRouteColor::getStatus, "active")
            .eq(ProductBomRouteColor::getDeletedFlag, 0))).isEmpty();
        if (!belongsToRoute) {
            throw validation("投产颜色不属于所选工艺路线");
        }
        boolean hasCost = !safe(costRepository.selectList(new LambdaQueryWrapper<ProductBomCostSnapshot>()
            .eq(ProductBomCostSnapshot::getProductBomId, bom.getProductBomId())
            .eq(ProductBomCostSnapshot::getProductBomRouteId, route.getProductBomRouteId())
            .in(ProductBomCostSnapshot::getStatus, List.of("current", "baseline"))
            .eq(ProductBomCostSnapshot::getDeletedFlag, 0))).isEmpty();
        if (!hasCost) {
            throw validation("投产颜色关联路线缺少有效成本快照");
        }
    }

    private boolean hasConfirmedOperation(Long projectId, ProductBomRoute route) {
        ProcessEntity routeProcess = processRepository.selectById(route.getProcessId());
        String currentVersion = routeProcess == null ? null : routeProcess.getVersionNo();
        return safe(operationRepository.selectList(new LambdaQueryWrapper<ProcessProductionOperationSelection>()
            .eq(ProcessProductionOperationSelection::getProductId, projectId)
            .eq(ProcessProductionOperationSelection::getProductBomRouteId, route.getProductBomRouteId())
            .eq(ProcessProductionOperationSelection::getStatus, "confirmed")
            .eq(ProcessProductionOperationSelection::getDeletedFlag, 0))).stream()
            .filter(selection -> sameRouteVersionOrLegacy(selection.getRouteVersionNo(), currentVersion))
            .anyMatch(selection -> validOperation(route, selection.getOperationProcessId()));
    }

    private boolean sameRouteVersionOrLegacy(String selectionVersion, String currentVersion) {
        if (!hasText(selectionVersion) || !hasText(currentVersion)) {
            return true;
        }
        return selectionVersion.trim().equals(currentVersion.trim());
    }

    private boolean hasText(String value) {
        return value != null && !value.isBlank();
    }

    private ProductionConfirmationVO.ApplicableColorVO toApplicableColorVO(ProductProductionColorDecision color) {
        String colorCode = firstNonBlank(color.getColorCode(), color.getColorName());
        String colorName = firstNonBlank(color.getColorName(), colorCode);
        return ProductionConfirmationVO.ApplicableColorVO.builder()
            .codeItemId(color.getCodeItemId())
            .colorCode(colorCode)
            .colorName(colorName)
            .build();
    }

    private boolean validOperation(ProductBomRoute route, Long operationId) {
        ProcessEntity operation = processRepository.selectById(operationId);
        return operation != null && route.getProcessId().equals(operation.getParentProcessId())
            && !Integer.valueOf(1).equals(operation.getDeletedFlag());
    }

    private List<ProductBom> activeProjectBoms(Long projectId) {
        return safe(bomRepository.selectList(new LambdaQueryWrapper<ProductBom>()
            .eq(ProductBom::getProductId, projectId)
            .notIn(ProductBom::getStatus, List.of("archived")).eq(ProductBom::getDeletedFlag, 0)));
    }

    private List<ProductBomRouteFormalSelection> activeFormalSelections(Long projectId) {
        return safe(formalSelectionRepository.selectList(new LambdaQueryWrapper<ProductBomRouteFormalSelection>()
            .eq(ProductBomRouteFormalSelection::getProductId, projectId)
            .eq(ProductBomRouteFormalSelection::getStatus, "active")
            .eq(ProductBomRouteFormalSelection::getDeletedFlag, 0))).stream()
            .filter(selection -> "active".equals(selection.getStatus()) && !Integer.valueOf(1).equals(selection.getDeletedFlag()))
            .toList();
    }

    private List<ProductBomRouteFormalSelection> activeFormalSelections(Long projectId, Long processId) {
        return safe(formalSelectionRepository.selectList(new LambdaQueryWrapper<ProductBomRouteFormalSelection>()
            .eq(ProductBomRouteFormalSelection::getProductId, projectId)
            .eq(ProductBomRouteFormalSelection::getProcessId, processId)
            .eq(ProductBomRouteFormalSelection::getStatus, "active")
            .eq(ProductBomRouteFormalSelection::getDeletedFlag, 0))).stream()
            .filter(selection -> "active".equals(selection.getStatus()) && !Integer.valueOf(1).equals(selection.getDeletedFlag()))
            .toList();
    }

    private List<ProductBomRoute> activeRoutes(Long bomId) {
        return safe(routeRepository.selectList(new LambdaQueryWrapper<ProductBomRoute>()
            .eq(ProductBomRoute::getProductBomId, bomId).eq(ProductBomRoute::getStatus, "active")
            .eq(ProductBomRoute::getDeletedFlag, 0)));
    }

    private List<ProductProductionColorDecision> confirmedColorDecisions(Long projectId) {
        return safe(colorRepository.selectList(new LambdaQueryWrapper<ProductProductionColorDecision>()
            .eq(ProductProductionColorDecision::getProductId, projectId)
            .eq(ProductProductionColorDecision::getSelectedFlag, 1)
            .eq(ProductProductionColorDecision::getStatus, "confirmed")
            .eq(ProductProductionColorDecision::getDeletedFlag, 0))).stream()
            .filter(value -> StringUtils.hasText(value.getColorName()) || StringUtils.hasText(value.getColorCode()))
            .sorted((left, right) -> colorKey(left.getColorCode(), left.getColorName()).compareTo(colorKey(right.getColorCode(), right.getColorName())))
            .toList();
    }

    private Product findSku(Product project, ProductProductionColorDecision decision) {
        List<Product> rows = safe(productRepository.selectList(new LambdaQueryWrapper<Product>()
            .eq(Product::getParentProductId, project.getProductId()).eq(Product::getProductType, "sku")
            .eq(Product::getDeletedFlag, 0)));
        String normalizedCode = normalizeCompactCode(decision.getColorCode());
        String normalizedName = trimToNull(decision.getColorName());
        String productCode = skuProductCode(project, decision);
        return rows.stream()
            .filter(sku -> StringUtils.hasText(normalizedCode)
                && Objects.equals(normalizedCode, normalizeCompactCode(sku.getColorCode())))
            .findFirst()
            .orElseGet(() -> rows.stream()
                .filter(sku -> StringUtils.hasText(normalizedName)
                    && Objects.equals(normalizedName, trimToNull(sku.getColor())))
                .findFirst()
                .orElseGet(() -> rows.stream()
                    .filter(sku -> Objects.equals(productCode, trimToNull(sku.getProductCode())))
                    .findFirst()
                    .orElse(null)));
    }

    private Product createSku(Product project, ProductProductionColorDecision decision, LocalDateTime now) {
        Product sku = new Product();
        sku.setParentProductId(project.getProductId());
        sku.setProductCode(uniqueSkuProductCode(project, decision));
        sku.setProductName(skuName(project, decision.getColorName()));
        sku.setProductType("sku");
        sku.setSeriesName(project.getSeriesName());
        sku.setModel(project.getModel());
        sku.setColor(trimToNull(decision.getColorName()));
        sku.setColorCode(normalizeCompactCode(decision.getColorCode()));
        sku.setProductSpecificCode(project.getProductSpecificCode());
        sku.setPhoneModelCode(project.getPhoneModelCode());
        sku.setFinishedProductCode(resolveAvailableFinishedProductCode(project, decision.getColorCode(), null));
        sku.setImportShortCode(project.getImportShortCode());
        sku.setMaterial(project.getMaterial());
        sku.setPackageType(project.getPackageType());
        sku.setSurfaceProcess(project.getSurfaceProcess());
        sku.setCoreProcess(project.getCoreProcess());
        sku.setComposition(project.getComposition());
        sku.setVersionNo(project.getVersionNo());
        sku.setStatus("released");
        sku.setReleasedAt(now);
        sku.setReleasedBy("system");
        sku.setCreatedAt(now);
        sku.setCreatedBy("system");
        sku.setUpdatedAt(now);
        sku.setUpdatedBy("system");
        sku.setDeletedFlag(0);
        return sku;
    }

    private boolean applySkuFields(Product sku, Product project, ProductProductionColorDecision decision, LocalDateTime now) {
        boolean changed = false;
        changed |= setIfDifferent(sku::getColor, sku::setColor, trimToNull(decision.getColorName()));
        changed |= setIfDifferent(sku::getColorCode, sku::setColorCode, normalizeCompactCode(decision.getColorCode()));
        changed |= setIfDifferent(sku::getProductSpecificCode, sku::setProductSpecificCode, project.getProductSpecificCode());
        changed |= setIfDifferent(sku::getPhoneModelCode, sku::setPhoneModelCode, project.getPhoneModelCode());
        String targetFinishedProductCode = resolveAvailableFinishedProductCode(project, decision.getColorCode(), sku.getProductId());
        if (StringUtils.hasText(targetFinishedProductCode) || !StringUtils.hasText(sku.getFinishedProductCode())) {
            changed |= setIfDifferent(sku::getFinishedProductCode, sku::setFinishedProductCode, targetFinishedProductCode);
        }
        changed |= setIfDifferent(sku::getImportShortCode, sku::setImportShortCode, project.getImportShortCode());
        if (changed) {
            sku.setUpdatedAt(now);
            sku.setUpdatedBy("system");
        }
        return changed;
    }

    private boolean applyProjectColor(Product project, List<ProductProductionColorDecision> decisions, LocalDateTime now) {
        List<String> colorNames = decisions.stream()
            .map(ProductProductionColorDecision::getColorName)
            .map(this::trimToNull)
            .filter(Objects::nonNull)
            .distinct()
            .toList();
        List<String> colorCodes = decisions.stream()
            .map(ProductProductionColorDecision::getColorCode)
            .map(this::normalizeCompactCode)
            .filter(StringUtils::hasText)
            .distinct()
            .toList();
        boolean singleColor = colorNames.size() == 1 && colorCodes.size() <= 1;
        boolean changed = setIfDifferent(project::getColor, project::setColor, String.join(",", colorNames));
        changed |= setIfDifferent(project::getColorCode, project::setColorCode, singleColor && !colorCodes.isEmpty() ? colorCodes.get(0) : null);
        if (changed) {
            project.setUpdatedAt(now);
            project.setUpdatedBy("system");
        }
        return changed;
    }

    private String resolveAvailableFinishedProductCode(Product project, String colorCode, Long currentSkuId) {
        String generated = resolveFinishedProductCode(project, colorCode);
        if (!StringUtils.hasText(generated)) {
            return null;
        }
        List<Product> conflicts = safe(productRepository.selectList(new LambdaQueryWrapper<Product>()
            .eq(Product::getFinishedProductCode, generated)
            .ne(currentSkuId != null, Product::getProductId, currentSkuId)
            .eq(Product::getDeletedFlag, 0)));
        boolean externalConflict = conflicts.stream()
            .anyMatch(conflict -> !Objects.equals(conflict.getProductId(), project.getProductId()));
        if (externalConflict) {
            return null;
        }
        releaseProjectFinishedProductCode(project, generated);
        return generated;
    }

    private String uniqueSkuProductCode(Product project, ProductProductionColorDecision decision) {
        String base = skuProductCode(project, decision);
        for (int attempt = 0; attempt < 100; attempt++) {
            String candidate = attempt == 0 ? base : base + "-" + attempt;
            Long count = productRepository.selectCount(new LambdaQueryWrapper<Product>()
                .eq(Product::getProductCode, candidate)
                .eq(Product::getDeletedFlag, 0));
            if (count == null || count == 0) {
                return candidate;
            }
        }
        return base + "-" + System.currentTimeMillis();
    }

    private String skuProductCode(Product project, ProductProductionColorDecision decision) {
        return project.getProductCode() + "-" + normalizedCode(firstText(decision.getColorCode(), decision.getColorName()));
    }

    private String resolveFinishedProductCode(Product project, String colorCode) {
        if (!StringUtils.hasText(project.getProductSpecificCode())
            || !StringUtils.hasText(project.getPhoneModelCode())
            || !StringUtils.hasText(colorCode)) {
            return null;
        }
        return businessCodeGenerator.generateProductStateCode(
            project.getProductSpecificCode(),
            resolveFinishedOperationCode(project),
            project.getPhoneModelCode(),
            colorCode
        );
    }

    private String resolveFinishedOperationCode(Product project) {
        String productSpecificCode = normalizeCompactCode(project.getProductSpecificCode());
        String operationFromProductCode = resolveProductLineOperationCode(project.getProductCode(), productSpecificCode);
        if (StringUtils.hasText(operationFromProductCode)) {
            return operationFromProductCode;
        }
        if (project.getParentProductId() != null) {
            Product parent = productRepository.selectById(project.getParentProductId());
            String operationFromParent = parent == null ? null : resolveProductLineOperationCode(parent.getProductCode(), productSpecificCode);
            if (StringUtils.hasText(operationFromParent)) {
                return operationFromParent;
            }
        }
        String operationFromFinishedCode = resolveFullFinishedOperationCode(
            project.getFinishedProductCode(),
            productSpecificCode,
            normalizeCompactCode(project.getPhoneModelCode())
        );
        return StringUtils.hasText(operationFromFinishedCode)
            ? operationFromFinishedCode
            : ProductBusinessCodeGenerator.DEFAULT_FINAL_OPERATION_CODE;
    }

    private String resolveProductLineOperationCode(String productCode, String productSpecificCode) {
        String normalized = normalizeCompactCode(productCode);
        if (!StringUtils.hasText(normalized) || !StringUtils.hasText(productSpecificCode)) {
            return null;
        }
        String prefix = ProductBusinessCodeGenerator.PRODUCT_STATE_PREFIX + productSpecificCode;
        if (!normalized.startsWith(prefix) || normalized.length() != prefix.length() + 4) {
            return null;
        }
        String operationCode = normalized.substring(prefix.length());
        return operationCode.matches("\\d{4}") ? operationCode : null;
    }

    private String resolveFullFinishedOperationCode(String finishedProductCode, String productSpecificCode, String phoneModelCode) {
        if (!StringUtils.hasText(finishedProductCode)) {
            return null;
        }
        try {
            ProductBusinessCodeGenerator.ProductStateCodeParts parts =
                businessCodeGenerator.parseProductStateCode(finishedProductCode);
            if (Objects.equals(parts.productSpecificCode(), productSpecificCode)
                && Objects.equals(parts.phoneModelCode(), phoneModelCode)) {
                return parts.operationCode();
            }
        } catch (BusinessException ignored) {
            return null;
        }
        return null;
    }

    private void releaseProjectFinishedProductCode(Product project, String generated) {
        if (!Objects.equals(trimToNull(project.getFinishedProductCode()), generated)) {
            return;
        }
        project.setFinishedProductCode(null);
        project.setUpdatedAt(LocalDateTime.now());
        project.setUpdatedBy("system");
        productRepository.updateById(project);
    }

    private boolean setIfDifferent(java.util.function.Supplier<String> getter,
                                   java.util.function.Consumer<String> setter,
                                   String value) {
        String normalizedValue = trimToNull(value);
        if (Objects.equals(trimToNull(getter.get()), normalizedValue)) {
            return false;
        }
        setter.accept(normalizedValue);
        return true;
    }

    private String firstText(String first, String second) {
        return StringUtils.hasText(first) ? first : second;
    }

    private String skuName(Product project, String colorName) {
        return java.util.stream.Stream.of(project.getProductName(), project.getModel(), trimToNull(colorName))
            .filter(StringUtils::hasText)
            .collect(Collectors.joining(" "));
    }

    private String colorKey(String colorCode, String colorName) {
        String code = normalizeCompactCode(colorCode);
        return StringUtils.hasText(code) ? code : Objects.toString(trimToNull(colorName), "");
    }

    private String trimToNull(String value) {
        return StringUtils.hasText(value) ? value.trim() : null;
    }

    private String normalizeCompactCode(String value) {
        return StringUtils.hasText(value) ? value.trim().toUpperCase(Locale.ROOT) : null;
    }

    private String normalizedCode(String colorName) {
        String code = colorName.trim().toUpperCase(Locale.ROOT).replaceAll("[^A-Z0-9]+", "-");
        return code.isBlank() ? Integer.toHexString(colorName.hashCode()).toUpperCase(Locale.ROOT) : code;
    }

    private void archiveOperations(Long productId, Long routeId) {
        for (ProcessProductionOperationSelection value : safe(operationRepository.selectList(
            new LambdaQueryWrapper<ProcessProductionOperationSelection>()
                .eq(ProcessProductionOperationSelection::getProductId, productId)
                .eq(ProcessProductionOperationSelection::getProductBomRouteId, routeId)
                .eq(ProcessProductionOperationSelection::getDeletedFlag, 0)))) {
            value.setStatus("archived");
            value.setDeletedFlag(1);
            value.setUpdatedAt(LocalDateTime.now());
            value.setUpdatedBy("system");
            operationRepository.updateById(value);
        }
    }

    private void archiveColors(Long productId) {
        for (ProductProductionColorDecision value : safe(colorRepository.selectList(
            new LambdaQueryWrapper<ProductProductionColorDecision>()
                .eq(ProductProductionColorDecision::getProductId, productId)
                .eq(ProductProductionColorDecision::getDeletedFlag, 0)))) {
            value.setStatus("archived");
            value.setDeletedFlag(1);
            value.setUpdatedAt(LocalDateTime.now());
            value.setUpdatedBy("system");
            colorRepository.updateById(value);
        }
    }

    private Product requireProject(Long projectId) {
        Product project = productRepository.selectById(projectId);
        if (project == null || Integer.valueOf(1).equals(project.getDeletedFlag())) {
            throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "项目不存在");
        }
        return project;
    }

    private BusinessException validation(String message) {
        return new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, message);
    }

    private <T> List<T> safe(List<T> values) {
        return values == null ? new ArrayList<>() : values;
    }

    private void fillCreate(com.yuewei.plm.repository.entity.BaseEntity value, LocalDateTime now) {
        value.setCreatedAt(now);
        value.setCreatedBy("system");
        value.setUpdatedAt(now);
        value.setUpdatedBy("system");
        value.setDeletedFlag(0);
    }
}
