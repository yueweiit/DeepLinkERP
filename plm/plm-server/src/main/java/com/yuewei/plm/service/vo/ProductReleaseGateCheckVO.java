package com.yuewei.plm.service.vo;

import java.util.List;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ProductReleaseGateCheckVO {

    private Long projectId;
    private Long productId;
    private Boolean passed;
    private Boolean blocking;
    private Boolean confirmRequired;
    private String currentStatus;
    private String currentNodeKey;
    private Boolean currentNodeConfirmed;
    private Integer frozenBomCount;
    private Integer lockedProcessRouteCount;
    private Integer drawingFileCount;
    private Integer sopFileCount;
    private Integer sipFileCount;
    private Integer testingFileCount;
    private List<ProductReleaseGateMissingItemVO> missingItems;
}
