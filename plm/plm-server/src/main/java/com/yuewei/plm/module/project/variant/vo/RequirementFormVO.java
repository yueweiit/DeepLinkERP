package com.yuewei.plm.module.project.variant.vo;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;
import com.yuewei.plm.module.integration.dingtalk.vo.MoldCodeMatchVO;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class RequirementFormVO {
    private Long projectId;
    private String dingTalkApprovalNo;
    private String productName;
    private String model;
    private String networkType;
    private String holeType;
    private String mobileFunction;
    private String tipo;
    private String priority;
    private String manufacturingLocation;
    private String moldMarking;
    private String productSpecificCode;
    private String phoneModelCode;
    private String materialCodes;
    private String moldCodes;
    private String moldMatchStatus;
    private List<MoldCodeMatchVO> moldMatches;
    private String referenceUrl;
    private String remark;
    private LocalDate expectedDeliveryDate;
    private String requirementType;
    private String customerRequirement;
    private String status;
    private List<ColorVO> colors;

    @Data @Builder
    public static class ColorVO {
        private Long variantColorId;
        private String colorCode;
        private String colorName;
        private LocalDateTime sourceConfirmedAt;
        private boolean selected;
    }
}
