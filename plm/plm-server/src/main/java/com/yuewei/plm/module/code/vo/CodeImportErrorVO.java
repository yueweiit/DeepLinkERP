package com.yuewei.plm.module.code.vo;

import lombok.AllArgsConstructor;
import lombok.Data;

@Data
@AllArgsConstructor
public class CodeImportErrorVO {
    private Integer rowNo;
    private String codeValue;
    private String field;
    private String reason;
}
