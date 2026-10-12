package com.yuewei.plm.module.process.vo;

import java.util.List;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ProcessRouteRelationVO {
    private Long processId;
    private String processCode;
    private String processName;
    private Long productId;
    private String productCode;
    private String productName;
    private String versionNo;
    private String status;
    private List<ProcessRouteColorVO> colors;
    private List<ProcessRouteSkuVO> skus;
    private List<ProcessOperationVO> operations;
    private List<LinkedBomRouteVO> linkedBomRoutes;
}
