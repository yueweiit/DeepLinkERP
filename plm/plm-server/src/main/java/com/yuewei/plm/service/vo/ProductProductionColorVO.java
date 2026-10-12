package com.yuewei.plm.service.vo;

import java.time.LocalDateTime;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ProductProductionColorVO {
    private Long codeItemId;
    private String colorCode;
    private String colorName;
    private LocalDateTime confirmedAt;
}
