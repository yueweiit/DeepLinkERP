package com.yuewei.plm.module.project.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class TimelineActionDTO {

    private String remark;
    private String reason;
    private Boolean returnToPrevious;
}
