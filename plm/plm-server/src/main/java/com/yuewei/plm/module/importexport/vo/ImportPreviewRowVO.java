package com.yuewei.plm.module.importexport.vo;

import java.util.Map;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ImportPreviewRowVO {
    private Integer rowNo;
    private String businessKey;
    private String status;
    private String message;
    private Map<String, String> values;
}
