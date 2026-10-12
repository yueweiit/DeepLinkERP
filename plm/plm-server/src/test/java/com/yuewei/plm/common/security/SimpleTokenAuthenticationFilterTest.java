package com.yuewei.plm.common.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.config.AppProperties;
import com.yuewei.plm.common.config.JacksonConfig;
import com.yuewei.plm.module.auth.service.TokenSessionService;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

class SimpleTokenAuthenticationFilterTest {

    @Test
    void missingTokenReturnsUnauthorizedJson() throws Exception {
        AppProperties appProperties = new AppProperties();
        appProperties.getSecurity().setEnabled(true);
        TokenSessionService tokenSessionService = mock(TokenSessionService.class);
        SimpleTokenAuthenticationFilter filter = new SimpleTokenAuthenticationFilter(
            appProperties,
            tokenSessionService,
            objectMapper()
        );
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/v1/operation-logs");
        request.setAttribute("requestId", "req-unauthorized");
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request, response, (servletRequest, servletResponse) -> {
        });

        assertThat(response.getStatus()).isEqualTo(401);
        assertThat(response.getContentAsString()).contains("\"code\":40101");
        assertThat(response.getContentAsString()).contains("未登录或登录已失效");
        assertThat(response.getContentAsString()).contains("\"requestId\":\"req-unauthorized\"");
    }

    @Test
    void validTokenSetsCurrentUserDuringFilterChain() throws Exception {
        AppProperties appProperties = new AppProperties();
        appProperties.getSecurity().setEnabled(true);
        TokenSessionService tokenSessionService = mock(TokenSessionService.class);
        CurrentUser user = new CurrentUser(1L, "engineer01", "工程部用户一", true);
        when(tokenSessionService.getCurrentUser("token-1")).thenReturn(Optional.of(user));
        SimpleTokenAuthenticationFilter filter = new SimpleTokenAuthenticationFilter(
            appProperties,
            tokenSessionService,
            objectMapper()
        );
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/v1/operation-logs");
        request.addHeader("Authorization", "Bearer token-1");
        MockHttpServletResponse response = new MockHttpServletResponse();
        filter.doFilter(request, response, (servletRequest, servletResponse) ->
            assertThat(CurrentUserContext.get()).contains(user)
        );

        assertThat(response.getStatus()).isEqualTo(200);
        assertThat(CurrentUserContext.get()).isEmpty();
    }

    private ObjectMapper objectMapper() {
        return new JacksonConfig().objectMapper();
    }
}
