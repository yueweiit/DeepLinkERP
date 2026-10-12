package com.yuewei.plm.module.bom.vo;

import java.util.List;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ProductionConfirmationVO {
    private Long productId;
    private Integer selectedOperationCount;
    private Integer selectedColorCount;
    private Integer createdSkuCount;
    private List<Long> operationProcessIds;
    private List<RouteSelectionVO> routeSelections;
    private List<String> colors;

    @Data
    @Builder
    public static class RouteSelectionVO {
        private Long processId;
        private Long productBomId;
        private Long productBomRouteId;
        private String routeName;
        private String bomVersionNo;
        private List<Long> operationProcessIds;
        private List<ApplicableColorVO> applicableColors;
    }

    @Data
    @Builder
    public static class ApplicableColorVO {
        private Long codeItemId;
        private String colorCode;
        private String colorName;
    }
}
