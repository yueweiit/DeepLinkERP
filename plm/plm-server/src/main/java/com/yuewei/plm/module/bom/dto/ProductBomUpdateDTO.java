package com.yuewei.plm.module.bom.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
public class ProductBomUpdateDTO {

    @NotBlank(message = "BOM名称不能为空")
    private String bomName;

    @NotBlank(message = "BOM类型不能为空")
    private String bomType;

    @NotBlank(message = "版本号不能为空")
    private String versionNo;

    private String remark;
}
