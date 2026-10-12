package com.yuewei.plm.module.health.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

public class ValidationProbeDTO {

    @NotBlank(message = "名称不能为空")
    @Size(max = 64, message = "名称长度不能超过 64")
    private String name;

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }
}
