package com.yuewei.plm.common.constant;

public final class ErrorCodeConstants {

    public static final int SUCCESS = 0;
    public static final int VALIDATION_ERROR = 40001;
    public static final int STATUS_TRANSITION_ILLEGAL = 40002;
    public static final int UNAUTHORIZED = 40101;
    public static final int FORBIDDEN = 40103;
    public static final int VERSION_FROZEN = 40301;
    public static final int VERSION_RELEASED = 40302;
    public static final int RELEASE_GATE_NOT_PASSED = 40307;
    public static final int RELEASE_RISK_CONFIRM_REQUIRED = 40308;
    public static final int RESOURCE_NOT_FOUND = 40401;
    public static final int ATTACHMENT_NOT_FOUND = 40402;
    public static final int CODE_CONFLICT = 40901;
    public static final int INTERNAL_ERROR = 50001;
    public static final int FILE_SIZE_EXCEEDED = 50002;
    public static final int FILE_SERVICE_ERROR = 50003;
    public static final int FILE_TYPE_NOT_SUPPORTED = 50004;
    public static final int UPSTREAM_UNAVAILABLE = 50301;

    private ErrorCodeConstants() {
    }
}
