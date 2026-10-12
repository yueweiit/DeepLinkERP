package com.yuewei.plm.module.bom.vo;

import java.math.BigDecimal;
import java.util.List;
import com.yuewei.plm.module.bom.dto.BomRouteColorDTO;
import lombok.Data;

@Data
public class BomImportRowVO {
    private Long productId;
    private String productCode;
    private String bomCode;
    private String sourceParentCode;
    private String sourceParentName;
    private String sourceStatus;
    private String sourceOrigin;
    private Integer componentCount;
    private Integer associatedSkuCount;
    private String versionNo;
    private Integer lineNo;
    private Long processId;
    private String routeCode;
    private String routeName;
    private List<String> colors;
    private List<BomRouteColorDTO> colorItems;
    private Long inventoryId;
    private String itemCode;
    private String itemName;
    private String specification;
    private String unit;
    private BigDecimal quantity;
    private BigDecimal lossRate;
    private BigDecimal unitCost;
    private BigDecimal lineCost;
    private String supplierCode;
    private String supplierName;
    private String currencyCode;
    private String materialSource;
    private Integer unmatchedFlag;
    private String lookupMessage;
    private Integer substituteFlag;
    private String remark;
}
