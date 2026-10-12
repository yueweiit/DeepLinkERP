package com.yuewei.plm.common.exception;

public class BusinessException extends RuntimeException {

    private final int code;
    private final Object data;

    public BusinessException(int code, String message) {
        super(message);
        this.code = code;
        this.data = null;
    }

    public BusinessException(int code, String message, Object data) {
        super(message);
        this.code = code;
        this.data = data;
    }

    public int getCode() {
        return code;
    }

    public Object getData() {
        return data;
    }
}
