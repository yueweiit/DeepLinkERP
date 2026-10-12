package com.yuewei.plm.module.bom.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.module.bom.dto.BomRouteSaveDTO;
import com.yuewei.plm.module.bom.dto.BomRouteColorDTO;
import com.yuewei.plm.module.bom.dto.ProductBomItemDTO;
import com.yuewei.plm.module.bom.dto.TestBomSaveDTO;
import com.yuewei.plm.module.bom.entity.ProductBom;
import com.yuewei.plm.module.bom.entity.ProductBomCostSnapshot;
import com.yuewei.plm.module.bom.entity.ProductBomItem;
import com.yuewei.plm.module.bom.entity.ProductBomRoute;
import com.yuewei.plm.module.bom.entity.ProductBomRouteColor;
import com.yuewei.plm.module.bom.repository.ProductBomCostSnapshotRepository;
import com.yuewei.plm.module.bom.repository.ProductBomItemRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteColorRepository;
import com.yuewei.plm.module.bom.repository.ProductBomRouteRepository;
import com.yuewei.plm.module.code.entity.CodeItem;
import com.yuewei.plm.module.code.service.CodeItemService;
import com.yuewei.plm.module.process.entity.ProcessEntity;
import com.yuewei.plm.module.process.repository.ProcessRepository;
import com.yuewei.plm.module.pilot.PilotAccessService;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class ProductBomWorkflowService {
    private static final String ACTIVE = "active";
    private static final String PROCESS_TYPE_ROUTING = "routing";
    private static final String DEFAULT_VARIANT = "BASE";

    private final ProductBomRepository bomRepository;
    private final ProductBomRouteRepository routeRepository;
    private final ProductBomRouteColorRepository colorRepository;
    private final ProductBomItemRepository itemRepository;
    private final ProductBomCostSnapshotRepository costRepository;
    private final BomCostCalculator costCalculator;
    private final BomTimelineGate timelineGate;
    private final CodeItemService codeItemService;
    private final ProcessRepository processRepository;
    private final ProductBomService productBomService;
    private final PilotAccessService access;

    @Transactional
    public ProductBom saveTestBom(Long productId, TestBomSaveDTO dto) {
        ProductBom bom = findTestBom(productId);
        LocalDateTime now = LocalDateTime.now();
        if (bom == null) {
            bom = new ProductBom();
            bom.setProductId(productId);
            bom.setBomCode("TEST-BOM-" + productId);
            bom.setBomName("测试 BOM");
            bom.setBomType("test");
            bom.setBomScope("test");
            bom.setSourceType("manual");
            bom.setStatus("draft");
            bom.setCurrencyCode("CNY");
            bom.setFrozenFlag(0);
            fillCreate(bom, now);
            bomRepository.insert(bom);
        } else if ("archived".equals(bom.getStatus())) {
            throw validation("已归档测试 BOM 不可修改");
        }
        bom.setVersionNo(dto.getVersionNo());
        bom.setStatus("draft");
        touch(bom);
        bomRepository.updateById(bom);
        List<ProductBomItem> existing = itemRepository.selectList(new LambdaQueryWrapper<ProductBomItem>()
            .eq(ProductBomItem::getProductBomId, bom.getProductBomId()).eq(ProductBomItem::getDeletedFlag, 0));
        boolean moneyEditable=access.hasPermission("finance:write");
        Map<Integer,ProductBomItem> originals=new HashMap<>();safeList(existing).forEach(item->originals.put(item.getLineNo(),item));
        if (existing != null) {
            existing.forEach(item -> {
                item.setDeletedFlag(1);
                touch(item);
                itemRepository.updateById(item);
            });
        }
        int index = 0;
        for (ProductBomItemDTO itemDTO : dto.getItems()) {
            int line=++index;ProductBomItem item = toTestItem(bom, itemDTO, line, now,
                originals.get(itemDTO.getLineNo()==null?line:itemDTO.getLineNo()),moneyEditable);
            itemRepository.insert(item);
        }
        return bom;
    }

    @Transactional
    public ProductBom confirmTestBom(Long productId) {
        ProductBom bom = findTestBom(productId);
        if (bom == null) {
            throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "测试 BOM 不存在");
        }
        List<ProductBomItem> items = itemRepository.selectList(new LambdaQueryWrapper<ProductBomItem>()
            .eq(ProductBomItem::getProductBomId, bom.getProductBomId()).eq(ProductBomItem::getDeletedFlag, 0));
        if (items == null || items.isEmpty()) {
            throw validation("测试 BOM 至少需要一条明细");
        }
        BomCostCalculator.Result cost = costCalculator.calculate(items, bom.getCurrencyCode(), null, null, null, null, null);
        bom.setTestTotalCost(cost.totalCost());
        bom.setCalculatedAt(LocalDateTime.now());
        bom.setConfirmedAt(bom.getCalculatedAt());
        bom.setConfirmedBy(operator());
        bom.setStatus("confirmed");
        touch(bom);
        bomRepository.updateById(bom);
        return bom;
    }

    @Transactional
    public void saveRoutes(Long bomId, List<BomRouteSaveDTO> routes) {
        ProductBom bom = requireEditable(bomId);
        validateRoutes(routes);
        boolean moneyEditable=access.hasPermission("finance:write");
        Map<SourceLine,ProductBomItem> originals=originalAmounts(bom,routes,moneyEditable);
        archiveExistingRoutes(bomId);
        LocalDateTime now = LocalDateTime.now();
        for (BomRouteSaveDTO dto : routes) {
            ProcessEntity processRoute = requireProductRoute(bom.getProductId(), dto.getProcessId());
            ProductBomRoute route = new ProductBomRoute();
            route.setProductBomId(bomId);
            route.setProductId(bom.getProductId());
            route.setProcessId(processRoute.getProcessId());
            route.setRouteCode(processRoute.getProcessCode());
            route.setRouteName(processRoute.getProcessName());
            route.setSharedBomGroupCode(blankToDefault(dto.getSharedBomGroupCode(), "BOM-" + bomId));
            route.setRouteVariantNo(blankToDefault(dto.getRouteVariantNo(), DEFAULT_VARIANT));
            route.setVariantName(blankToDefault(dto.getVariantName(), "基础用料"));
            Long origin=dto.getProductBomRouteId()!=null?dto.getProductBomRouteId():dto.getSourceProductBomRouteId();
            route.setVariantSourceType(origin == null ? "manual" : "copied");
            route.setSourceProductBomRouteId(origin);
            route.setStatus(ACTIVE);
            fillCreate(route, now);
            routeRepository.insert(route);
            for (BomRouteColorDTO selected : normalizedColors(dto)) {
                CodeItem code = codeItemService.requireEnabledColor(selected.getCodeItemId(), selected.getCodeValue());
                ProductBomRouteColor color = new ProductBomRouteColor();
                color.setProductBomId(bomId);
                color.setProductBomRouteId(route.getProductBomRouteId());
                color.setCodeItemId(code.getCodeItemId());
                color.setColorCode(code.getCodeValue());
                color.setColorName(code.getCodeName());
                color.setStatus(ACTIVE);
                fillCreate(color, now);
                colorRepository.insert(color);
            }
            for (ProductBomItemDTO itemDTO : dto.getItems()) {
                Long source=dto.getProductBomRouteId()!=null?dto.getProductBomRouteId():dto.getSourceProductBomRouteId();
                ProductBomItem item = toItem(bom, route, itemDTO, now,
                    source==null?null:originals.get(new SourceLine(source,itemDTO.getLineNo())),moneyEditable);
                itemRepository.insert(item);
            }
        }
    }

    @Transactional
    public List<ProductBomCostSnapshot> recalculateCosts(Long bomId, List<BomRouteSaveDTO> costInputs) {
        ProductBom bom = requireEditable(bomId);
        List<ProductBomRoute> routes = activeRoutes(bomId);
        List<BomRouteSaveDTO> inputs = costInputs == null ? List.of() : costInputs;
        return routes.stream().map(route -> {
            List<ProductBomItem> items = activeItems(route.getProductBomRouteId());
            BomRouteSaveDTO input = inputs.stream()
                .filter(value -> value.getProductBomRouteId() != null
                    ? value.getProductBomRouteId().equals(route.getProductBomRouteId())
                    : value.getProcessId() != null && value.getProcessId().equals(route.getProcessId()))
                .findFirst()
                .orElse(new BomRouteSaveDTO());
            BomCostCalculator.Result result = costCalculator.calculate(
                items, bom.getCurrencyCode(), input.getProcessCost(), input.getPackageCost(), input.getLaborCost(),
                input.getToolingCost(), input.getOtherCost()
            );
            archiveCurrentCost(bomId, route.getProductBomRouteId());
            ProductBomCostSnapshot snapshot = snapshot(bom, route, result);
            costRepository.insert(snapshot);
            return snapshot;
        }).toList();
    }

    @Transactional
    public ProductBom submitReview(Long bomId) {
        ProductBom bom = requireEditable(bomId);
        requireCompleteRoutes(bomId, true);
        bom.setStatus("reviewing");
        touch(bom);
        bomRepository.updateById(bom);
        return bom;
    }

    @Transactional
    public ProductBom freeze(Long bomId) {
        ProductBom bom = requireBom(bomId);
        timelineGate.requireFreezeOrPublishNode(bom.getProductId());
        if (!List.of("draft", "released", "frozen").contains(bom.getStatus())) {
            throw validation("只有草稿、已冻结或已发布的正式 BOM 可以冻结");
        }
        requireCompleteRoutes(bomId, true);
        bom.setFrozenFlag(1);
        if (!"released".equals(bom.getStatus())) {
            bom.setStatus("frozen");
        }
        bom.setFrozenAt(LocalDateTime.now());
        bom.setFrozenBy(operator());
        touch(bom);
        bomRepository.updateById(bom);
        return bom;
    }

    @Transactional
    public ProductBom publish(Long bomId) {
        ProductBom bom = requireBom(bomId);
        timelineGate.requireFreezeOrPublishNode(bom.getProductId());
        if (!List.of("reviewing", "frozen", "released").contains(bom.getStatus())) {
            throw validation("请先提交审核；只有审核中、已冻结或已发布的正式 BOM 可以发布");
        }
        requireCompleteRoutes(bomId, true);
        // Both existing public actions use the same formal selection, audit and durable release transaction.
        if("released".equals(bom.getStatus()))return bom;
        productBomService.confirmCurrentVersion(bomId,null);
        return requireBom(bomId);
    }

    private void validateRoutes(List<BomRouteSaveDTO> routes) {
        if (routes == null || routes.isEmpty()) {
            throw validation("正式 BOM 至少需要一条有效工艺路线");
        }
        Set<String> assignedColors = new HashSet<>();
        Set<String> assignedVariants = new HashSet<>();
        Map<String, Long> groupProcessIds = new HashMap<>();
        for (BomRouteSaveDTO route : routes) {
            String groupCode = blankToDefault(route.getSharedBomGroupCode(), "DEFAULT");
            Long groupProcessId = groupProcessIds.putIfAbsent(groupCode, route.getProcessId());
            if (groupProcessId != null && !groupProcessId.equals(route.getProcessId())) {
                throw validation("同一套 BOM 的颜色副本必须绑定同一条工艺路线");
            }
            String variantKey = groupCode
                + ":" + blankToDefault(route.getRouteVariantNo(), DEFAULT_VARIANT);
            if (!assignedVariants.add(variantKey)) {
                throw validation("同一套 BOM 的副本编号不能重复");
            }
            if ((route.getColorItems() == null || route.getColorItems().isEmpty())
                && (route.getColors() == null || route.getColors().isEmpty())) {
                throw validation("工艺路线至少需要一个适用颜色");
            }
            if (route.getItems() == null || route.getItems().isEmpty()) {
                throw validation("颜色副本至少需要一条 BOM 明细");
            }
            for (BomRouteColorDTO color : normalizedColors(route)) {
                String normalized = color.getCodeValue() == null ? "" : color.getCodeValue().trim();
                if (normalized.isEmpty()) {
                    throw validation("适用颜色不能为空");
                }
                if (!assignedColors.add(normalized)) {
                    throw new BusinessException(ErrorCodeConstants.CODE_CONFLICT,
                        "颜色编码 " + normalized + " 不能同时归属多条有效工艺路线");
                }
            }
        }
    }

    private String blankToDefault(String value, String defaultValue) {
        return value == null || value.isBlank() ? defaultValue : value.trim();
    }

    private List<BomRouteColorDTO> normalizedColors(BomRouteSaveDTO route) {
        if (route.getColorItems() != null && !route.getColorItems().isEmpty()) return route.getColorItems();
        return route.getColors().stream().map(name -> {
            BomRouteColorDTO value = new BomRouteColorDTO();
            value.setCodeItemId(null); value.setCodeValue(name); value.setCodeName(name);
            return value;
        }).toList();
    }

    private ProcessEntity requireProductRoute(Long productId, Long processId) {
        ProcessEntity route = processRepository.selectById(processId);
        if (route == null || Integer.valueOf(1).equals(route.getDeletedFlag())) {
            throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "工艺路线不存在");
        }
        if (!productId.equals(route.getProductId()) || !PROCESS_TYPE_ROUTING.equals(route.getProcessType())) {
            throw validation("请选择当前产品下已有的有效工艺路线");
        }
        if ("archived".equals(route.getStatus())) {
            throw validation("工艺路线已归档，不能关联 BOM");
        }
        return route;
    }

    private void requireCompleteRoutes(Long bomId, boolean requireCost) {
        List<ProductBomRoute> routes = activeRoutes(bomId);
        if (routes.isEmpty()) {
            throw validation("正式 BOM 至少需要一条有效工艺路线");
        }
        for (ProductBomRoute route : routes) {
            if (activeColors(route.getProductBomRouteId()).isEmpty()) {
                throw validation("路线 " + route.getRouteName() + " 缺少适用颜色");
            }
            if (activeItems(route.getProductBomRouteId()).isEmpty()) {
                throw validation("路线 " + route.getRouteName() + " 缺少 BOM 明细");
            }
            if (requireCost && currentCosts(bomId, route.getProductBomRouteId()).isEmpty()) {
                throw validation("路线 " + route.getRouteName() + " 尚未完成成本计算");
            }
        }
    }

    private record SourceLine(Long routeId,Integer lineNo) {}

    /** Capture stable server-side values before archiving in fixed-size batches, never name/amount matching. */
    private Map<SourceLine,ProductBomItem> originalAmounts(ProductBom bom,List<BomRouteSaveDTO> inputs,boolean canWrite) {
        List<ProductBomRoute> current=safeList(routeRepository.selectList(new LambdaQueryWrapper<ProductBomRoute>()
            .eq(ProductBomRoute::getProductBomId,bom.getProductBomId()).eq(ProductBomRoute::getDeletedFlag,0)));
        Map<Long,ProductBomRoute> known=new HashMap<>();current.forEach(route->known.put(route.getProductBomRouteId(),route));Set<Long> currentIds=new HashSet<>(known.keySet());
        Set<Long> requested=new HashSet<>();for(var dto:inputs){Long id=dto.getProductBomRouteId()!=null?dto.getProductBomRouteId():dto.getSourceProductBomRouteId();if(id!=null)requested.add(id);}
        Set<Long> missing=new HashSet<>(requested);missing.removeAll(known.keySet());
        if(!missing.isEmpty())safeList(routeRepository.selectList(new LambdaQueryWrapper<ProductBomRoute>().in(ProductBomRoute::getProductBomRouteId,missing))).forEach(route->known.put(route.getProductBomRouteId(),route));
        for(var dto:inputs){Long id=dto.getProductBomRouteId()!=null?dto.getProductBomRouteId():dto.getSourceProductBomRouteId();if(id==null)continue;
            ProductBomRoute source=known.get(id);if(source==null)throw validation("原金额路线不存在，不能猜测价格来源");
            if(dto.getProductBomRouteId()!=null){
                if(!java.util.Objects.equals(source.getProductId(),bom.getProductId())||!java.util.Objects.equals(source.getProductBomId(),bom.getProductBomId()))throw validation("当前路线 ID 不属于此 BOM，请使用明确的复制来源路线");
                if(dto.getSourceProductBomRouteId()!=null&&!java.util.Objects.equals(dto.getSourceProductBomRouteId(),source.getSourceProductBomRouteId()))throw validation("复制来源与当前路线的服务器记录不一致，请刷新确认");
            }else if(!java.util.Objects.equals(source.getProductId(),bom.getProductId())&&!(java.util.Objects.equals(source.getProductId(),bom.getSourceProductId())&&java.util.Objects.equals(source.getProductBomId(),bom.getSourceProductBomId())))throw validation("原金额路线不属于当前项目或已确认继承来源，不能猜测价格来源");
        }
        Map<SourceLine,ProductBomItem> result=new HashMap<>();
        var itemQuery=new LambdaQueryWrapper<ProductBomItem>().and(w->w.eq(ProductBomItem::getProductBomId,bom.getProductBomId()).eq(ProductBomItem::getDeletedFlag,0)
            .or(!known.isEmpty()).in(!known.isEmpty(),ProductBomItem::getProductBomRouteId,known.keySet()));
        for(ProductBomItem item:safeList(itemRepository.selectList(itemQuery))){
            if(!canWrite&&java.util.Objects.equals(item.getProductBomId(),bom.getProductBomId())&&BomAmountPolicy.priced(item)&&!known.containsKey(item.getProductBomRouteId()))throw validation("已有含金额明细缺少稳定原路线 ID，不能在保存时覆盖；请财务先核对关联");
            ProductBomRoute route=known.get(item.getProductBomRouteId());if(route==null)continue;
            if(!Integer.valueOf(1).equals(route.getDeletedFlag())&&Integer.valueOf(1).equals(item.getDeletedFlag()))continue;
            if(result.putIfAbsent(new SourceLine(item.getProductBomRouteId(),item.getLineNo()),item)!=null)throw validation("原路线行号有歧义，请先核对，不能按名称或金额匹配");
        }
        if(!canWrite){Set<Long> protectedRoutes=new HashSet<>();for(var entry:result.entrySet())if(BomAmountPolicy.priced(entry.getValue())&&currentIds.contains(entry.getKey().routeId()))protectedRoutes.add(entry.getKey().routeId());
            Set<Long> stable=new HashSet<>();for(var dto:inputs){Long id=dto.getProductBomRouteId()!=null?dto.getProductBomRouteId():dto.getSourceProductBomRouteId();if(id!=null)stable.add(id);}protectedRoutes.removeAll(stable);
            if(!protectedRoutes.isEmpty())throw validation("已有含金额路线缺少稳定原路线 ID，不能通过省略金额覆盖；请刷新后保留路线关联");
        }
        return result;
    }

    private ProductBomItem toItem(ProductBom bom, ProductBomRoute route, ProductBomItemDTO dto, LocalDateTime now,ProductBomItem source,boolean moneyEditable) {
        if (dto.getQuantity() == null || dto.getQuantity().compareTo(BigDecimal.ZERO) <= 0) {
            throw validation("BOM 明细用量必须大于 0");
        }
        if (dto.getLossRate() != null
            && (dto.getLossRate().compareTo(BigDecimal.ZERO) < 0 || dto.getLossRate().compareTo(BigDecimal.ONE) > 0)) {
            throw validation("损耗率必须在 0 到 1 之间");
        }
        ProductBomItem item = new ProductBomItem();
        BomAmountPolicy.apply(dto,item,source,moneyEditable,bom.getCurrencyCode());
        item.setProductBomId(bom.getProductBomId());
        item.setProductBomRouteId(route.getProductBomRouteId());
        item.setSharedBomGroupCode(route.getSharedBomGroupCode());
        item.setProductId(bom.getProductId());
        item.setInventoryId(dto.getInventoryId());
        item.setItemCode(dto.getItemCode());
        item.setItemName(dto.getItemName());
        item.setSpecification(dto.getSpecification());
        item.setLineNo(dto.getLineNo());
        item.setQuantity(dto.getQuantity());
        item.setUnit(dto.getUnit());
        item.setLossRate(dto.getLossRate() == null ? BigDecimal.ZERO : dto.getLossRate());
        item.setSupplierCodeSnapshot(dto.getSupplierCode());
        item.setSupplierNameSnapshot(dto.getSupplierName());
        item.setSubstituteFlag(dto.getSubstituteFlag() == null ? 0 : dto.getSubstituteFlag());
        item.setRemark(dto.getRemark());
        item.setVersionNo(bom.getVersionNo());
        item.setStatus("draft");
        item.setMaterialSource(normalizeMaterialSource(dto));
        item.setUnmatchedFlag(normalizeUnmatchedFlag(dto, item.getMaterialSource()));
        fillCreate(item, now);
        return item;
    }

    private String normalizeMaterialSource(ProductBomItemDTO dto) {
        if (hasText(dto.getMaterialSource())) {
            return dto.getMaterialSource().trim();
        }
        return Integer.valueOf(1).equals(dto.getUnmatchedFlag()) ? "manual" : "inventory";
    }

    private Integer normalizeUnmatchedFlag(ProductBomItemDTO dto, String materialSource) {
        if (dto.getUnmatchedFlag() != null) {
            return dto.getUnmatchedFlag();
        }
        return "manual".equals(materialSource) ? 1 : 0;
    }

    private boolean hasText(String value) {
        return value != null && !value.isBlank();
    }

    private ProductBomItem toTestItem(ProductBom bom, ProductBomItemDTO dto, int fallbackLineNo, LocalDateTime now,ProductBomItem source,boolean moneyEditable) {
        ProductBomRoute placeholder = new ProductBomRoute();
        placeholder.setProductBomRouteId(null);
        ProductBomItem item = toItem(bom, placeholder, dto, now,source,moneyEditable);
        item.setProductBomRouteId(null);
        if (item.getLineNo() == null) item.setLineNo(fallbackLineNo);
        return item;
    }

    private ProductBom findTestBom(Long productId) {
        return bomRepository.selectOne(new LambdaQueryWrapper<ProductBom>()
            .eq(ProductBom::getProductId, productId).eq(ProductBom::getBomScope, "test")
            .eq(ProductBom::getDeletedFlag, 0).orderByDesc(ProductBom::getProductBomId).last("limit 1"));
    }

    private ProductBomCostSnapshot snapshot(ProductBom bom, ProductBomRoute route, BomCostCalculator.Result value) {
        ProductBomCostSnapshot snapshot = new ProductBomCostSnapshot();
        snapshot.setProductBomId(bom.getProductBomId());
        snapshot.setProductBomRouteId(route.getProductBomRouteId());
        snapshot.setProductId(bom.getProductId());
        snapshot.setVersionNo(bom.getVersionNo());
        snapshot.setMaterialCost(value.materialCost());
        snapshot.setLossCost(value.lossCost());
        snapshot.setProcessCost(value.processCost());
        snapshot.setPackageCost(value.packageCost());
        snapshot.setLaborCost(value.laborCost());
        snapshot.setToolingCost(value.toolingCost());
        snapshot.setOtherCost(value.otherCost());
        snapshot.setTotalCost(value.totalCost());
        snapshot.setCurrencyCode(bom.getCurrencyCode() == null ? "CNY" : bom.getCurrencyCode());
        snapshot.setSourceSnapshotJson("{}");
        snapshot.setCalculatedAt(LocalDateTime.now());
        snapshot.setStatus("current");
        fillCreate(snapshot, snapshot.getCalculatedAt());
        return snapshot;
    }

    private ProductBom requireEditable(Long bomId) {
        ProductBom bom = requireBom(bomId);
        if (Set.of("released", "frozen", "archived").contains(bom.getStatus()) || Integer.valueOf(1).equals(bom.getFrozenFlag())) {
            throw new BusinessException(ErrorCodeConstants.VERSION_FROZEN, "已发布、冻结或归档 BOM 不可修改，请复制为新版本");
        }
        return bom;
    }

    private ProductBom requireBom(Long bomId) {
        ProductBom bom = bomRepository.selectById(bomId);
        if (bom == null || Integer.valueOf(1).equals(bom.getDeletedFlag())) {
            throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "BOM 不存在");
        }
        return bom;
    }

    private List<ProductBomRoute> activeRoutes(Long bomId) {
        return safeList(routeRepository.selectList(new LambdaQueryWrapper<ProductBomRoute>()
            .eq(ProductBomRoute::getProductBomId, bomId).eq(ProductBomRoute::getStatus, ACTIVE)
            .eq(ProductBomRoute::getDeletedFlag, 0)));
    }

    private List<ProductBomRouteColor> activeColors(Long routeId) {
        return safeList(colorRepository.selectList(new LambdaQueryWrapper<ProductBomRouteColor>()
            .eq(ProductBomRouteColor::getProductBomRouteId, routeId).eq(ProductBomRouteColor::getStatus, ACTIVE)
            .eq(ProductBomRouteColor::getDeletedFlag, 0)));
    }

    private List<ProductBomItem> activeItems(Long routeId) {
        return safeList(itemRepository.selectList(new LambdaQueryWrapper<ProductBomItem>()
            .eq(ProductBomItem::getProductBomRouteId, routeId).eq(ProductBomItem::getDeletedFlag, 0)));
    }

    private List<ProductBomCostSnapshot> currentCosts(Long bomId, Long routeId) {
        return safeList(costRepository.selectList(new LambdaQueryWrapper<ProductBomCostSnapshot>()
            .eq(ProductBomCostSnapshot::getProductBomId, bomId)
            .eq(ProductBomCostSnapshot::getProductBomRouteId, routeId)
            .eq(ProductBomCostSnapshot::getStatus, "current")
            .eq(ProductBomCostSnapshot::getDeletedFlag, 0)));
    }

    private void archiveExistingRoutes(Long bomId) {
        List<ProductBomRoute> existing = routeRepository.selectList(new LambdaQueryWrapper<ProductBomRoute>()
            .eq(ProductBomRoute::getProductBomId, bomId).eq(ProductBomRoute::getDeletedFlag, 0));
        if (existing == null) {
            return;
        }
        existing.forEach(route -> {
            route.setDeletedFlag(1);
            route.setStatus("inactive");
            touch(route);
            routeRepository.updateById(route);
        });
        List<ProductBomRouteColor> colors = colorRepository.selectList(new LambdaQueryWrapper<ProductBomRouteColor>()
            .eq(ProductBomRouteColor::getProductBomId, bomId).eq(ProductBomRouteColor::getDeletedFlag, 0));
        if (colors != null) {
            colors.forEach(color -> {
                color.setDeletedFlag(1);
                color.setStatus("inactive");
                touch(color);
                colorRepository.updateById(color);
            });
        }
        List<ProductBomItem> items = itemRepository.selectList(new LambdaQueryWrapper<ProductBomItem>()
            .eq(ProductBomItem::getProductBomId, bomId).eq(ProductBomItem::getDeletedFlag, 0));
        if (items != null) {
            items.forEach(item -> {
                item.setDeletedFlag(1);
                touch(item);
                itemRepository.updateById(item);
            });
        }
    }

    private void archiveCurrentCost(Long bomId, Long routeId) {
        List<ProductBomCostSnapshot> existing = currentCosts(bomId, routeId);
        existing.forEach(snapshot -> {
            snapshot.setStatus("history");
            touch(snapshot);
            costRepository.updateById(snapshot);
        });
    }

    private void fillCreate(com.yuewei.plm.repository.entity.BaseEntity entity, LocalDateTime now) {
        entity.setCreatedAt(now);
        entity.setCreatedBy(operator());
        entity.setUpdatedAt(now);
        entity.setUpdatedBy(operator());
        entity.setDeletedFlag(0);
    }

    private void touch(com.yuewei.plm.repository.entity.BaseEntity entity) {
        entity.setUpdatedAt(LocalDateTime.now());
        entity.setUpdatedBy(operator());
    }

    private String operator() {
        return com.yuewei.plm.common.security.CurrentUserContext.get().map(com.yuewei.plm.common.security.CurrentUser::username)
            .orElseThrow(() -> new BusinessException(40101, "请先登录，BOM 修改必须记录实际账号"));
    }

    private BusinessException validation(String message) {
        return new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, message);
    }

    private <T> List<T> safeList(List<T> values) {
        return values == null ? List.of() : values;
    }
}
