package com.yuewei.plm.common.util;

import com.yuewei.plm.common.filter.RequestContextFilter;
import jakarta.servlet.http.HttpServletRequest;
import java.util.UUID;
import org.springframework.util.StringUtils;

public final class RequestIdUtil {

    public static final String REQUEST_ID_HEADER = "X-Request-Id";

    private RequestIdUtil() {
    }

    public static String getRequestId(HttpServletRequest request) {
        if (request == null) {
            return UUID.randomUUID().toString();
        }
        Object attribute = request.getAttribute(RequestContextFilter.REQUEST_ID_ATTRIBUTE);
        if (attribute instanceof String requestId && StringUtils.hasText(requestId)) {
            return requestId;
        }
        String requestId = request.getHeader(REQUEST_ID_HEADER);
        return StringUtils.hasText(requestId) ? requestId : UUID.randomUUID().toString();
    }
}
