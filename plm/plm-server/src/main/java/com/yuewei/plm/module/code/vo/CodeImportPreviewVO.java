package com.yuewei.plm.module.code.vo;

import java.util.List;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class CodeImportPreviewVO {
    private String importToken;
    private Integer createCount;
    private Integer updateCount;
    private Integer unchangedCount;
    private Integer errorCount;
    private Integer committedCount;
    private List<CodeImportRowVO> rows;
    private List<CodeImportErrorVO> errors;
}
