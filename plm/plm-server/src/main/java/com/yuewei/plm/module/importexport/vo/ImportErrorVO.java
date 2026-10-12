package com.yuewei.plm.module.importexport.vo;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ImportErrorVO {
    private Integer rowNo;
    private String businessKey;
    private String fieldName;
    private String rawValue;
    private String errorMessage;
}
