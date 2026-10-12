package com.yuewei.plm.module.project.dto;

import java.time.LocalDateTime;
import lombok.Data;

@Data
public class MoldTransferExpressSaveDTO {
    private String trackingNo;
    private LocalDateTime shippedAt;
}
