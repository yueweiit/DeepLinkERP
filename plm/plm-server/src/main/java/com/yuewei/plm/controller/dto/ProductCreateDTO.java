package com.yuewei.plm.controller.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class ProductCreateDTO {

    private Long customerId;

    private Long parentProductId;

    @NotBlank(message = "产品名称不能为空")
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

    @NotBlank(message = "产品类型不能为空")
    @Pattern(regexp = "product_line|model_variant", message = "产品类型仅支持 product_line 或 model_variant")
    private String productType;

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

    private Long ownerUserId;

    @NotBlank(message = "版本号不能为空")
    @Size(max = 32, message = "版本号长度不能超过32")
    private String versionNo;

    @NotNull(message = "创建人不能为空")
    @Size(max = 64, message = "创建人长度不能超过64")
    private String createdBy;

    @Size(max = 255, message = "备注长度不能超过255")
    private String remark;
}
