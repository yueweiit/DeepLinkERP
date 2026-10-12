package com.yuewei.plm.module.process.vo;

import java.util.List;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ProcessRouteTemplateVO {

    private String routeTemplateCode;
    private String routeTemplateName;
    private String productCode;
    private String versionNo;
    private String status;
    private Boolean defaultTemplate;
    private Integer priority;
    private List<ProcessRouteTemplateOperationVO> operations;
}
