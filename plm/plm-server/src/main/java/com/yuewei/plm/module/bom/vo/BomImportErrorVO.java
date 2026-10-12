package com.yuewei.plm.module.bom.vo;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class BomImportErrorVO {
    private Integer rowNo;
    private String field;
    private String originalValue;
    private String reason;
}
