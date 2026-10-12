package com.yuewei.plm.module.project.dto;

import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import lombok.Data;

@Data
public class ProjectCostItemCreateDTO {
    @NotBlank(message = "成本分类不能为空")
    private String costCategory;

    @NotBlank(message = "成本名称不能为空")
    private String costName;

    @NotNull(message = "金额不能为空")
    @DecimalMin(value = "0", message = "金额不能为负数")
    private BigDecimal amount;

    private String currencyCode;
    private String supplierName;
    private LocalDateTime occurredAt;
    private String remark;
}
