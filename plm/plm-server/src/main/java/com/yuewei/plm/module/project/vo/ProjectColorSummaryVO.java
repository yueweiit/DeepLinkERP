package com.yuewei.plm.module.project.vo;

import java.util.List;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ProjectColorSummaryVO {
    private Integer skuColorCount;
    private Integer productionColorCount;
    private List<ColorUsageVO> skuColors;
    private List<ColorUsageVO> productionColors;
    private List<ColorUsageVO> skuOnlyColors;
    private List<ColorUsageVO> productionOnlyColors;

    @Data
    @Builder
    public static class ColorUsageVO {
        private String colorCode;
        private String colorName;
        private Integer skuCount;
        private Integer decisionCount;
    }
}
