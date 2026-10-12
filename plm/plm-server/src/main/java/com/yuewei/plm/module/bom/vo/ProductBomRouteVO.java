package com.yuewei.plm.module.bom.vo;

import java.math.BigDecimal;
import java.util.List;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ProductBomRouteVO {
    private Long productBomRouteId;
    private Long productBomId;
    private Long processId;
    private String routeCode;
    private String routeName;
    private String sharedBomGroupCode;
    private String routeVariantNo;
    private String variantName;
    private Long sourceProductBomRouteId;
    private String status;
    private List<String> colors;
    private List<ProductBomRouteColorVO> colorItems;
    private List<ProductBomItemVO> items;
    private ProductBomCostSnapshotVO costSnapshot;
    private BigDecimal skuUnitCost;
}
