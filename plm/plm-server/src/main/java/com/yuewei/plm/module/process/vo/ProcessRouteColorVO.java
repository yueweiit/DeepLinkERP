package com.yuewei.plm.module.process.vo;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ProcessRouteColorVO {
    private Long codeItemId;
    private String colorCode;
    private String colorName;
}
