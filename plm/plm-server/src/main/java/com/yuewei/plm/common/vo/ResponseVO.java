package com.yuewei.plm.common.vo;

import com.yuewei.plm.common.constant.ErrorCodeConstants;
import java.time.OffsetDateTime;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ResponseVO<T> {

    private int code;
    private String message;
    private T data;
    private String requestId;
    private OffsetDateTime timestamp;

    public static <T> ResponseVO<T> success(T data, String requestId, OffsetDateTime timestamp) {
        return ResponseVO.<T>builder()
            .code(ErrorCodeConstants.SUCCESS)
            .message("success")
            .data(data)
            .requestId(requestId)
            .timestamp(timestamp)
            .build();
    }

    public static ResponseVO<Void> success(String requestId, OffsetDateTime timestamp) {
        return success(null, requestId, timestamp);
    }

    public static <T> ResponseVO<T> created(T data, String requestId, OffsetDateTime timestamp) {
        return ResponseVO.<T>builder()
            .code(ErrorCodeConstants.SUCCESS)
            .message("created")
            .data(data)
            .requestId(requestId)
            .timestamp(timestamp)
            .build();
    }

    public static <T> ResponseVO<T> error(int code, String message, String requestId, OffsetDateTime timestamp) {
        return ResponseVO.<T>builder()
            .code(code)
            .message(message)
            .requestId(requestId)
            .timestamp(timestamp)
            .build();
    }

    public static <T> ResponseVO<T> error(int code, String message, T data, String requestId, OffsetDateTime timestamp) {
        return ResponseVO.<T>builder()
            .code(code)
            .message(message)
            .data(data)
            .requestId(requestId)
            .timestamp(timestamp)
            .build();
    }
}
