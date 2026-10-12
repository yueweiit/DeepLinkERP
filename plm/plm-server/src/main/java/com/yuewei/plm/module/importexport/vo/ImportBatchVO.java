package com.yuewei.plm.module.importexport.vo;

import java.time.LocalDateTime;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ImportBatchVO {
    private Long importBatchId;
    private String objectType;
    private String fileName;
    private Integer totalCount;
    private Integer successCount;
    private Integer failCount;
    private String status;
    private String remark;
    private LocalDateTime createdAt;
    private String createdBy;
}
