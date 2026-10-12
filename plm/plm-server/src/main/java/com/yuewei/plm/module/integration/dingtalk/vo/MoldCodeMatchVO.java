package com.yuewei.plm.module.integration.dingtalk.vo;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class MoldCodeMatchVO {
    private String moldCode;
    private String expectedMoldCode;
    private String productSpecificCode;
    private String materialCode;
    private String phoneModelCode;
    private String matchStatus;
    private Long inventoryId;
    private String message;
}
