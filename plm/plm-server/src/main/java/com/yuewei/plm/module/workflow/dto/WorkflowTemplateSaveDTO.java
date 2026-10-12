package com.yuewei.plm.module.workflow.dto;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import java.util.ArrayList;
import java.util.List;
import lombok.Data;

@Data
public class WorkflowTemplateSaveDTO {

    @NotBlank
    private String flowType;
    @NotBlank
    private String templateName;
    private String versionNo;
    private String status;
    private String description;
    @Valid
    @NotEmpty
    private List<WorkflowTemplateNodeSaveDTO> nodes = new ArrayList<>();
}
