package com.yuewei.plm.module.inventory.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import java.util.List;
import lombok.Data;

@Data
public class SupplierSupplySideSaveDTO {

    @Size(max = 64, message = "供应商编码最长64位")
    private String supplierCode;

    @NotBlank(message = "供应商名称不能为空")
    @Size(max = 255, message = "供应商名称最长255位")
    private String supplierName;

    @Size(max = 128, message = "供应商简称最长128位")
    private String shortName;

    @NotBlank(message = "联系人不能为空")
    @Size(max = 128, message = "联系人最长128位")
    private String contactPerson;

    @NotBlank(message = "联系电话不能为空")
    @Size(max = 64, message = "联系电话最长64位")
    private String contactPhone;

    @Size(max = 128, message = "联系邮箱最长128位")
    private String contactEmail;

    @NotBlank(message = "所在区域不能为空")
    @Size(max = 128, message = "所在区域最长128位")
    private String region;

    @NotEmpty(message = "供应品类不能为空")
    private List<@NotBlank(message = "供应品类不能为空") String> supplyCategories;

    @Size(max = 128, message = "付款条件最长128位")
    private String paymentTerm;

    @Size(max = 128, message = "合作等级最长128位")
    private String cooperationLevel;

    @Size(max = 32, message = "交期风险最长32位")
    private String deliveryRisk;

    @Pattern(regexp = "draft|active|inactive", message = "供应商状态只能是draft、active或inactive")
    private String status = "draft";
}
