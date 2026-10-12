package com.yuewei.plm.common.exception;

import static org.assertj.core.api.Assertions.assertThat;

import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.vo.ResponseVO;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.servlet.resource.NoResourceFoundException;

class GlobalExceptionHandlerTest {

    @Test
    void noResourceFoundReturnsResourceNotFoundError() {
        GlobalExceptionHandler handler = new GlobalExceptionHandler();
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/");
        request.setAttribute("requestId", "req-not-found");
        NoResourceFoundException exception = new NoResourceFoundException(HttpMethod.GET, "/");

        ResponseVO<Void> response = handler.handleNoResourceFound(exception, request);

        assertThat(response.getCode()).isEqualTo(ErrorCodeConstants.RESOURCE_NOT_FOUND);
        assertThat(response.getMessage()).isEqualTo("资源不存在");
        assertThat(response.getRequestId()).isEqualTo("req-not-found");
    }

    @Test
    void businessExceptionCanReturnStructuredData() {
        GlobalExceptionHandler handler = new GlobalExceptionHandler();
        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/api/v1/projects/10/publish");
        request.setAttribute("requestId", "req-gate");
        Map<String, String> data = Map.of("code", "BOM_NOT_FROZEN");
        BusinessException exception = new BusinessException(
            ErrorCodeConstants.RELEASE_GATE_NOT_PASSED,
            "发布门禁未通过",
            data
        );

        ResponseEntity<ResponseVO<Object>> entity = handler.handleBusiness(exception, request);
        ResponseVO<Object> response = entity.getBody();

        assertThat(entity.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(response).isNotNull();
        assertThat(response.getCode()).isEqualTo(ErrorCodeConstants.RELEASE_GATE_NOT_PASSED);
        assertThat(response.getMessage()).isEqualTo("发布门禁未通过");
        assertThat(response.getData()).isEqualTo(data);
        assertThat(response.getRequestId()).isEqualTo("req-gate");
    }

    @Test
    void unauthorizedBusinessExceptionReturnsHttpUnauthorized() {
        GlobalExceptionHandler handler = new GlobalExceptionHandler();
        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/api/v1/projects/9/timeline/node/return");
        BusinessException exception = new BusinessException(ErrorCodeConstants.UNAUTHORIZED, "unauthorized");

        ResponseEntity<ResponseVO<Object>> response = handler.handleBusiness(exception, request);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
        assertThat(response.getBody()).isNotNull();
        assertThat(response.getBody().getCode()).isEqualTo(ErrorCodeConstants.UNAUTHORIZED);
    }

    @Test
    void forbiddenBusinessExceptionReturnsHttpForbidden() {
        GlobalExceptionHandler handler = new GlobalExceptionHandler();
        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/api/v1/projects/9/timeline/node/return");
        BusinessException exception = new BusinessException(ErrorCodeConstants.FORBIDDEN, "forbidden");

        ResponseEntity<ResponseVO<Object>> response = handler.handleBusiness(exception, request);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.FORBIDDEN);
        assertThat(response.getBody()).isNotNull();
        assertThat(response.getBody().getCode()).isEqualTo(ErrorCodeConstants.FORBIDDEN);
    }

    @Test
    void malformedJsonReturnsValidationErrorInsteadOfInternalServerError() {
        GlobalExceptionHandler handler = new GlobalExceptionHandler();
        MockHttpServletRequest request = new MockHttpServletRequest("PUT", "/api/v1/boms/1/routes");
        request.setAttribute("requestId", "req-json");
        HttpMessageNotReadableException exception = new HttpMessageNotReadableException("Unknown field productBomRouteId");

        ResponseVO<Void> response = handler.handleMessageNotReadable(exception, request);

        assertThat(response.getCode()).isEqualTo(ErrorCodeConstants.VALIDATION_ERROR);
        assertThat(response.getMessage()).isEqualTo("请求体 JSON 格式或字段不符合接口契约");
        assertThat(response.getRequestId()).isEqualTo("req-json");
    }
}
