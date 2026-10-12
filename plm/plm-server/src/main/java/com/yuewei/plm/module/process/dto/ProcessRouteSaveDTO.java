package com.yuewei.plm.module.process.dto;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import java.util.List;
import lombok.Data;

@Data
public class ProcessRouteSaveDTO {

    @NotBlank(message = "工艺路线名称不能为空")
    private String processName;

    @NotBlank(message = "版本号不能为空")
    private String versionNo;

    private String routeTemplateCode;
    private String routeTemplateVersion;
    private Boolean copyTemplateOperations;
    private String applicableModel;
    private String applicableColor;
    private String linkedBomVersionNo;
    private Boolean finalSelected;
    private String remark;

    @Valid
    private List<ProcessOperationDTO> operations;
}
