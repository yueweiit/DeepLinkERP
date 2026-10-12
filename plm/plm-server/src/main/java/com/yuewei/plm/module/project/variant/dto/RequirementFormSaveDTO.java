package com.yuewei.plm.module.project.variant.dto;

import java.time.LocalDate;
import java.util.List;
import lombok.Data;

@Data
public class RequirementFormSaveDTO {
    private String model;
    private String networkType;
    private String holeType;
    private String mobileFunction;
    private String tipo;
    private String priority;
    private String manufacturingLocation;
    private String moldMarking;
    private String referenceUrl;
    private String remark;
    private LocalDate expectedDeliveryDate;
    private String requirementType;
    private String customerRequirement;
    private List<Long> selectedVariantColorIds;
    private String operator = "system";
}
