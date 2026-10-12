package com.yuewei.plm.module.operationlog.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.AssertTrue;
import java.time.LocalDateTime;
import lombok.Data;
import org.springframework.format.annotation.DateTimeFormat;

@Data
public class OperationLogQueryDTO {

    @Min(1)
    private long page = 1;

    @Min(1)
    @Max(200)
    private long size = 20;

    private Long operatorUserId;
    private String action;
    private String businessType;
    private String businessId;
    private String requestId;

    @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME)
    private LocalDateTime createdFrom;
    @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME)
    private LocalDateTime createdTo;

    @AssertTrue(message = "日志开始时间不得晚于结束时间")
    public boolean isDateRangeValid() {
        return createdFrom == null || createdTo == null || !createdFrom.isAfter(createdTo);
    }
}
