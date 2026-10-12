package com.yuewei.plm.module.importexport.vo;

import java.util.List;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ImportPreviewVO {
    private String importToken;
    private String objectType;
    private String fileName;
    private Integer totalCount;
    private Integer successCount;
    private Integer failCount;
    private List<ImportPreviewRowVO> rows;
    private List<ImportErrorVO> errors;
}
