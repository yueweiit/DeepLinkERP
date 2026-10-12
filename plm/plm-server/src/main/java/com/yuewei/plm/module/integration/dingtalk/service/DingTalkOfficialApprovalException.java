package com.yuewei.plm.module.integration.dingtalk.service;

public class DingTalkOfficialApprovalException extends RuntimeException {
    private final String errorCode;

    public DingTalkOfficialApprovalException(String errorCode, String message) {
        super(message);
        this.errorCode = errorCode;
    }

    public String getErrorCode() {
        return errorCode;
    }
}
