package com.yuewei.plm.controller.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.time.LocalDate;
import java.time.LocalDateTime;
import lombok.Data;

@Data
public class ProductUpdateDTO {

    @NotBlank(message = "更新人不能为空")
    @Size(max = 64, message = "更新人长度不能超过64")
    private String updatedBy;

    @Size(max = 255, message = "产品名称长度不能超过255")
    private String productName;

    @Size(max = 20)
    private String productSpecificCode;

    @Size(max = 20)
    private String phoneModelCode;

    @Size(max = 20)
    private String colorCode;

    @Size(max = 80)
    private String finishedProductCode;

    @Size(max = 20)
    private String importShortCode;

    @Size(max = 128, message = "系列名称长度不能超过128")
    private String seriesName;

    @Size(max = 128, message = "型号长度不能超过128")
    private String model;

    @Size(max = 64, message = "颜色长度不能超过64")
    private String color;

    @Size(max = 128, message = "材料长度不能超过128")
    private String material;

    @Size(max = 128, message = "包装类型长度不能超过128")
    private String packageType;

    @Size(max = 128, message = "表面工艺长度不能超过128")
    private String surfaceProcess;

    @Size(max = 255, message = "核心工艺长度不能超过255")
    private String coreProcess;

    private String composition;
    private LocalDate expectedDeliveryDate;
    private LocalDateTime expectedArrivalAt;
    private LocalDateTime actualArrivalAt;
    private String networkType;
    private String holeType;
    private String mobileFunction;
    private String tipo;
    private String priority;
    private String manufacturingLocation;
    private String moldMarking;
    private String referenceUrl;
    private String requirementType;
    private String customerRequirement;
    private String remark;
}
