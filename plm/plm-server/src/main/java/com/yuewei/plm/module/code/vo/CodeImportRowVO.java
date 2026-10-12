package com.yuewei.plm.module.code.vo;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class CodeImportRowVO {
    private Integer rowNo;
    private String codeValue;
    private String codeName;
    private String codeNameZh;
    private String status;
    private Integer sortOrder;
    private String action;
}
