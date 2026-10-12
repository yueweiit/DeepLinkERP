package com.yuewei.plm.module.process.vo;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ProcessMetricCardVO {
    private String label;
    private Object value;
    private String hint;
}
