package com.yuewei.plm.common.exception;

import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.ConstraintViolationException;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.AuthenticationException;
import org.springframework.validation.FieldError;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.servlet.resource.NoResourceFoundException;

@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(BusinessException.class)
    public ResponseEntity<ResponseVO<Object>> handleBusiness(BusinessException ex, HttpServletRequest request) {
        ResponseVO<Object> body;
        if (ex.getData() != null) {
            body = ResponseVO.error(ex.getCode(), ex.getMessage(), ex.getData(), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
        } else {
            body = ResponseVO.error(ex.getCode(), ex.getMessage(), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
        }
        HttpStatus status = switch (ex.getCode()) {
            case ErrorCodeConstants.UNAUTHORIZED -> HttpStatus.UNAUTHORIZED;
            case ErrorCodeConstants.FORBIDDEN -> HttpStatus.FORBIDDEN;
            case ErrorCodeConstants.RESOURCE_NOT_FOUND -> HttpStatus.NOT_FOUND;
            case ErrorCodeConstants.CODE_CONFLICT -> HttpStatus.CONFLICT;
            case ErrorCodeConstants.UPSTREAM_UNAVAILABLE -> HttpStatus.SERVICE_UNAVAILABLE;
            default -> HttpStatus.BAD_REQUEST;
        };
        return ResponseEntity.status(status).body(body);
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public ResponseVO<Map<String, List<Map<String, String>>>> handleValidation(MethodArgumentNotValidException ex,
                                                                               HttpServletRequest request) {
        List<Map<String, String>> errors = ex.getBindingResult()
            .getFieldErrors()
            .stream()
            .map(this::toFieldError)
            .toList();
        return ResponseVO.error(
            ErrorCodeConstants.VALIDATION_ERROR,
            "参数校验失败",
            Map.of("errors", errors),
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }

    @ExceptionHandler(ConstraintViolationException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public ResponseVO<Void> handleConstraint(ConstraintViolationException ex, HttpServletRequest request) {
        return ResponseVO.error(
            ErrorCodeConstants.VALIDATION_ERROR,
            ex.getMessage(),
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public ResponseVO<Void> handleMessageNotReadable(HttpMessageNotReadableException ex, HttpServletRequest request) {
        return ResponseVO.error(
            ErrorCodeConstants.VALIDATION_ERROR,
            "请求体 JSON 格式或字段不符合接口契约",
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }

    @ExceptionHandler(AuthenticationException.class)
    @ResponseStatus(HttpStatus.UNAUTHORIZED)
    public ResponseVO<Void> handleAuthentication(AuthenticationException ex, HttpServletRequest request) {
        return ResponseVO.error(
            ErrorCodeConstants.UNAUTHORIZED,
            "未登录或登录已失效",
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }

    @ExceptionHandler(AccessDeniedException.class)
    @ResponseStatus(HttpStatus.FORBIDDEN)
    public ResponseVO<Void> handleAccessDenied(AccessDeniedException ex, HttpServletRequest request) {
        return ResponseVO.error(
            ErrorCodeConstants.FORBIDDEN,
            "无权限访问",
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }

    @ExceptionHandler(NoResourceFoundException.class)
    @ResponseStatus(HttpStatus.NOT_FOUND)
    public ResponseVO<Void> handleNoResourceFound(NoResourceFoundException ex, HttpServletRequest request) {
        return ResponseVO.error(
            ErrorCodeConstants.RESOURCE_NOT_FOUND,
            "资源不存在",
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }

    @ExceptionHandler(Exception.class)
    @ResponseStatus(HttpStatus.INTERNAL_SERVER_ERROR)
    public ResponseVO<Void> handleUnknown(Exception ex, HttpServletRequest request) {
        log.error("Unhandled exception", ex);
        return ResponseVO.error(
            ErrorCodeConstants.INTERNAL_ERROR,
            "服务器内部错误",
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }

    private Map<String, String> toFieldError(FieldError fieldError) {
        return Map.of(
            "field", fieldError.getField(),
            "message", fieldError.getDefaultMessage() == null ? "参数错误" : fieldError.getDefaultMessage()
        );
    }
}
