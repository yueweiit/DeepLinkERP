package com.yuewei.plm.module.bom.vo;

import java.util.List;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class BomHistoryMergeCandidateVO {
    private Long productId;
    private String productCode;
    private String productName;
    private Long processId;
    private String routeName;
    private String routeVariantNo;
    private String bomType;
    private List<Long> candidateBomIds;
    private List<String> candidateVersions;
    private List<String> colors;
    private Integer commonItemCount;
    private Integer colorDiffItemCount;
    private String riskLevel;
    private Boolean canAutoMerge;
    private String reason;
    private Long mainProductBomId;
    private Long mainProductBomRouteId;
}
