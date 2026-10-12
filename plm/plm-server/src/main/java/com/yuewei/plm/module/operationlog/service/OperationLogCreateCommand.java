package com.yuewei.plm.module.operationlog.service;

import jakarta.servlet.http.HttpServletRequest;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class OperationLogCreateCommand {

    private String action;
    private String businessType;
    private String businessId;
    private String businessCode;
    private String businessName;
    private String detailJson;
    private HttpServletRequest request;
}
