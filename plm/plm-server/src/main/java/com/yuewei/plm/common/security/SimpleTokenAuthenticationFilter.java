package com.yuewei.plm.common.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.config.AppProperties;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.auth.service.TokenSessionService;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.time.OffsetDateTime;
import java.util.List;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
public class SimpleTokenAuthenticationFilter extends OncePerRequestFilter {

    private static final String BEARER_PREFIX = "Bearer ";
    private final AppProperties appProperties;
    private final TokenSessionService tokenSessionService;
    private final ObjectMapper objectMapper;

    public SimpleTokenAuthenticationFilter(AppProperties appProperties,
                                           TokenSessionService tokenSessionService,
                                           ObjectMapper objectMapper) {
        this.appProperties = appProperties;
        this.tokenSessionService = tokenSessionService;
        this.objectMapper = objectMapper;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {
        if (!appProperties.getSecurity().isEnabled() || isPublicPath(request.getRequestURI())) {
            filterChain.doFilter(request, response);
            return;
        }

        try {
            String token = parseBearerToken(request.getHeader("Authorization"));
            CurrentUser user = tokenSessionService.getCurrentUser(token).orElse(null);
            if (user == null) {
                // M1 直接在过滤器返回统一 JSON，避免 Spring Security 默认跳转或 HTML 错误页影响 Apifox 验收。
                writeUnauthorized(response, request);
                return;
            }

            CurrentUserContext.set(user);
            UsernamePasswordAuthenticationToken authentication = new UsernamePasswordAuthenticationToken(
                user,
                null,
                List.of(new SimpleGrantedAuthority("ROLE_ENGINEER"))
            );
            SecurityContextHolder.getContext().setAuthentication(authentication);
            filterChain.doFilter(request, response);
        } finally {
            CurrentUserContext.clear();
            SecurityContextHolder.clearContext();
        }
    }

    private String parseBearerToken(String authorization) {
        if (!StringUtils.hasText(authorization) || !authorization.startsWith(BEARER_PREFIX)) {
            return null;
        }
        String token = authorization.substring(BEARER_PREFIX.length());
        return StringUtils.hasText(token) ? token : null;
    }

    private void writeUnauthorized(HttpServletResponse response, HttpServletRequest request) throws IOException {
        response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
        response.setContentType("application/json;charset=UTF-8");
        ResponseVO<Void> body = ResponseVO.error(
            ErrorCodeConstants.UNAUTHORIZED,
            "未登录或登录已失效",
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
        objectMapper.writeValue(response.getWriter(), body);
    }

    private boolean isPublicPath(String path) {
        return path.startsWith("/api/v1/health")
            || path.equals("/api/v1/auth/login")
            || path.equals("/api/v1/pilot/dingtalk/login")
            || path.equals("/api/v1/pilot/dingtalk/status")
            || path.equals("/api/v1/integrations/dingtalk/approval-callbacks")
            || path.equals("/api/v1/integrations/dingtalk/outbound")
            || path.equals("/api/dingtalk/outbound")
            || path.startsWith("/swagger-ui")
            || path.startsWith("/v3/api-docs");
    }
}
