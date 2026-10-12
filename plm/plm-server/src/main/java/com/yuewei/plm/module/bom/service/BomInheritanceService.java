package com.yuewei.plm.module.bom.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
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
import com.yuewei.plm.module.process.entity.ProcessEntity;
import com.yuewei.plm.module.process.repository.ProcessRepository;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.BaseEntity;
import com.yuewei.plm.repository.entity.Product;
import java.time.LocalDateTime;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class BomInheritanceService {
    private final ProductRepository productRepository;
    private final ProductBomRepository bomRepository;
    private final ProductBomRouteRepository routeRepository;
    private final ProductBomRouteColorRepository colorRepository;
    private final ProductBomItemRepository itemRepository;
    private final ProductBomCostSnapshotRepository costRepository;
    private final ProcessRepository processRepository;

    @Transactional
    public ProductBom inheritLatestReleasedAllColors(Long sourceProductId, Long targetProductId) {
        ProductBom source = latestReleasedFormalBom(sourceProductId);
        List<ProductBomRoute> routes = routeRepository.selectList(new LambdaQueryWrapper<ProductBomRoute>()
            .eq(ProductBomRoute::getProductBomId, source.getProductBomId())
            .eq(ProductBomRoute::getStatus, "active")
            .eq(ProductBomRoute::getDeletedFlag, 0));
        Set<String> colors = new HashSet<>();
        if (routes != null) routes.forEach(route -> activeColors(route.getProductBomRouteId())
            .forEach(color -> colors.add(color.getColorName())));
        if (colors.isEmpty()) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "父产品正式 BOM 没有有效颜色，不能创建新型号项目");
        }
        return inherit(source.getProductBomId(), targetProductId, List.copyOf(colors));
    }

    @Transactional
    public ProductBom inheritLatestReleasedByColors(Long sourceProductId, Long targetProductId, List<String> selectedColors) {
        return inheritLatestReleasedByColors(sourceProductId, targetProductId, selectedColors, Map.of());
    }

    @Transactional
    public ProductBom inheritLatestReleasedByColors(Long sourceProductId, Long targetProductId, List<String> selectedColors,
                                                    Map<Long, Long> processIdMapping) {
        ProductBom source = latestReleasedFormalBom(sourceProductId);
        return inherit(source.getProductBomId(), targetProductId, selectedColors, null, processIdMapping);
    }

    private ProductBom latestReleasedFormalBom(Long sourceProductId) {
        List<ProductBom> sources = bomRepository.selectList(new LambdaQueryWrapper<ProductBom>()
            .eq(ProductBom::getProductId, sourceProductId)
            .eq(ProductBom::getBomScope, "formal")
            .eq(ProductBom::getStatus, "released")
            .eq(ProductBom::getDeletedFlag, 0)
            .orderByDesc(ProductBom::getUpdatedAt));
        if (sources == null || sources.isEmpty()) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "父产品没有已发布正式 BOM，不能创建新型号项目");
        }
        return sources.get(0);
    }

    @Transactional
    public ProductBom inherit(Long sourceBomId, Long targetProductId, List<String> selectedColors) {
        return inherit(sourceBomId, targetProductId, selectedColors, null);
    }

    @Transactional
    public ProductBom copyVersion(Long sourceBomId, String versionNo, List<String> selectedColors) {
        ProductBom source = bomRepository.selectById(sourceBomId);
        if (source == null) {
            throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "来源 BOM 不存在");
        }
        return inherit(sourceBomId, source.getProductId(), selectedColors, versionNo);
    }

    private ProductBom inherit(
        Long sourceBomId, Long targetProductId, List<String> selectedColors, String targetVersionNo
    ) {
        return inherit(sourceBomId, targetProductId, selectedColors, targetVersionNo, Map.of());
    }

    private ProductBom inherit(
        Long sourceBomId, Long targetProductId, List<String> selectedColors, String targetVersionNo,
        Map<Long, Long> processIdMapping
    ) {
        ProductBom source = bomRepository.selectById(sourceBomId);
        if (source == null || !"released".equals(source.getStatus())) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "只能继承已发布正式 BOM");
        }
        Product target = productRepository.selectById(targetProductId);
        if (target == null || Integer.valueOf(1).equals(target.getDeletedFlag())) {
            throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "目标新型号不存在");
        }
        Set<String> selected = new HashSet<>(selectedColors == null ? List.of() : selectedColors);
        if (selected.isEmpty()) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "至少选择一个生产颜色");
        }
        LocalDateTime now = LocalDateTime.now();
        ProductBom targetBom = copyBom(source, targetProductId, targetVersionNo, now);
        bomRepository.insert(targetBom);

        List<ProductBomRoute> sourceRoutes = routeRepository.selectList(new LambdaQueryWrapper<ProductBomRoute>()
            .eq(ProductBomRoute::getProductBomId, sourceBomId)
            .eq(ProductBomRoute::getStatus, "active")
            .eq(ProductBomRoute::getDeletedFlag, 0));
        for (ProductBomRoute sourceRoute : sourceRoutes) {
            List<ProductBomRouteColor> selectedRouteColors = activeColors(sourceRoute.getProductBomRouteId()).stream()
                .filter(color -> selected.contains(color.getColorName()))
                .toList();
            if (selectedRouteColors.isEmpty()) {
                continue;
            }
            ProductBomRoute targetRoute = copyRoute(sourceRoute, targetBom, now, processIdMapping);
            routeRepository.insert(targetRoute);
            selectedRouteColors.forEach(sourceColor -> colorRepository.insert(copyColor(sourceColor, targetBom, targetRoute, now)));
            List<ProductBomItem> sourceItems = itemRepository.selectList(new LambdaQueryWrapper<ProductBomItem>()
                .eq(ProductBomItem::getProductBomRouteId, sourceRoute.getProductBomRouteId())
                .eq(ProductBomItem::getDeletedFlag, 0));
            if (sourceItems != null) {
                sourceItems.forEach(sourceItem -> itemRepository.insert(copyItem(sourceItem, targetBom, targetRoute, now)));
            }
            List<ProductBomCostSnapshot> sourceCosts = costRepository.selectList(
                new LambdaQueryWrapper<ProductBomCostSnapshot>()
                    .eq(ProductBomCostSnapshot::getProductBomRouteId, sourceRoute.getProductBomRouteId())
                    .eq(ProductBomCostSnapshot::getStatus, "current")
                    .eq(ProductBomCostSnapshot::getDeletedFlag, 0)
            );
            if (sourceCosts != null) {
                sourceCosts.forEach(sourceCost -> costRepository.insert(copyCost(sourceCost, targetBom, targetRoute, now)));
            }
        }
        return targetBom;
    }

    private List<ProductBomRouteColor> activeColors(Long routeId) {
        List<ProductBomRouteColor> values = colorRepository.selectList(new LambdaQueryWrapper<ProductBomRouteColor>()
            .eq(ProductBomRouteColor::getProductBomRouteId, routeId)
            .eq(ProductBomRouteColor::getStatus, "active")
            .eq(ProductBomRouteColor::getDeletedFlag, 0));
        return values == null ? List.of() : values;
    }

    private ProductBom copyBom(ProductBom source, Long targetProductId, String targetVersionNo, LocalDateTime now) {
        ProductBom target = new ProductBom();
        target.setProductId(targetProductId);
        target.setBomCode("BOM-" + targetProductId + "-" + System.currentTimeMillis());
        target.setBomName(source.getBomName());
        target.setBomType(source.getBomType());
        target.setBomScope("candidate");
        target.setSourceType("inherited");
        target.setSourceProductId(source.getProductId());
        target.setSourceProductBomId(source.getProductBomId());
        target.setVersionNo(targetVersionNo == null ? source.getVersionNo() : targetVersionNo);
        target.setStatus("draft");
        target.setFrozenFlag(0);
        target.setCurrencyCode(source.getCurrencyCode() == null ? "CNY" : source.getCurrencyCode());
        fillCreate(target, now);
        return target;
    }

    private ProductBomRoute copyRoute(ProductBomRoute source, ProductBom targetBom, LocalDateTime now,
                                      Map<Long, Long> processIdMapping) {
        ProductBomRoute target = new ProductBomRoute();
        Long sourceProcessId = source.getProcessId();
        Long targetProcessId = sourceProcessId == null
            ? null
            : processIdMapping.getOrDefault(sourceProcessId, sourceProcessId);
        ProcessEntity inheritedProcess = sourceProcessId != null && processIdMapping.containsKey(sourceProcessId)
            ? processRepository.selectById(targetProcessId)
            : null;
        target.setProductBomId(targetBom.getProductBomId());
        target.setProductId(targetBom.getProductId());
        target.setProcessId(targetProcessId);
        target.setRouteCode(inheritedProcess == null ? source.getRouteCode() : inheritedProcess.getProcessCode());
        target.setRouteName(inheritedProcess == null ? source.getRouteName() : inheritedProcess.getProcessName());
        target.setSharedBomGroupCode(source.getSharedBomGroupCode());
        target.setRouteVariantNo(source.getRouteVariantNo());
        target.setVariantName(source.getVariantName());
        target.setVariantSourceType("inherited");
        target.setStatus("active");
        target.setSourceProductBomRouteId(source.getProductBomRouteId());
        fillCreate(target, now);
        return target;
    }

    private ProductBomRouteColor copyColor(
        ProductBomRouteColor source, ProductBom targetBom, ProductBomRoute targetRoute, LocalDateTime now
    ) {
        ProductBomRouteColor target = new ProductBomRouteColor();
        target.setProductBomId(targetBom.getProductBomId());
        target.setProductBomRouteId(targetRoute.getProductBomRouteId());
        target.setCodeItemId(source.getCodeItemId());
        target.setColorCode(source.getColorCode());
        target.setColorName(source.getColorName());
        target.setStatus("active");
        fillCreate(target, now);
        return target;
    }

    private ProductBomItem copyItem(
        ProductBomItem source, ProductBom targetBom, ProductBomRoute targetRoute, LocalDateTime now
    ) {
        ProductBomItem target = new ProductBomItem();
        target.setProductBomId(targetBom.getProductBomId());
        target.setProductBomRouteId(targetRoute.getProductBomRouteId());
        target.setSharedBomGroupCode(targetRoute.getSharedBomGroupCode());
        target.setProductId(targetBom.getProductId());
        target.setInventoryId(source.getInventoryId());
        target.setItemCode(source.getItemCode());
        target.setItemName(source.getItemName());
        target.setSpecification(source.getSpecification());
        target.setLineNo(source.getLineNo());
        target.setQuantity(source.getQuantity());
        target.setUnit(source.getUnit());
        target.setLossRate(source.getLossRate());
        target.setSubstituteFlag(source.getSubstituteFlag());
        target.setUnitCostSnapshot(source.getUnitCostSnapshot());
        target.setCurrencyCode(source.getCurrencyCode());
        target.setVersionNo(targetBom.getVersionNo());
        target.setStatus("draft");
        fillCreate(target, now);
        return target;
    }

    private ProductBomCostSnapshot copyCost(
        ProductBomCostSnapshot source, ProductBom targetBom, ProductBomRoute targetRoute, LocalDateTime now
    ) {
        ProductBomCostSnapshot target = new ProductBomCostSnapshot();
        target.setProductBomId(targetBom.getProductBomId());
        target.setProductBomRouteId(targetRoute.getProductBomRouteId());
        target.setProductId(targetBom.getProductId());
        target.setVersionNo(targetBom.getVersionNo());
        target.setMaterialCost(source.getMaterialCost());
        target.setLossCost(source.getLossCost());
        target.setProcessCost(source.getProcessCost());
        target.setPackageCost(source.getPackageCost());
        target.setLaborCost(source.getLaborCost());
        target.setToolingCost(source.getToolingCost());
        target.setOtherCost(source.getOtherCost());
        target.setTotalCost(source.getTotalCost());
        target.setCurrencyCode(source.getCurrencyCode());
        target.setSourceSnapshotJson(source.getSourceSnapshotJson());
        target.setCalculatedAt(source.getCalculatedAt());
        target.setStatus("baseline");
        fillCreate(target, now);
        return target;
    }

    private void fillCreate(BaseEntity entity, LocalDateTime now) {
        entity.setCreatedAt(now);
        entity.setCreatedBy("system");
        entity.setUpdatedAt(now);
        entity.setUpdatedBy("system");
        entity.setDeletedFlag(0);
    }
}
