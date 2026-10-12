package com.yuewei.plm.module.bom.vo;

import java.util.List;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class BomImportPreviewVO {
    private String importToken;
    private String status;
    private Integer totalRows;
    private Integer validRows;
    private Integer errorRows;
    private List<BomImportRowVO> rows;
    private List<BomImportErrorVO> errors;
}
