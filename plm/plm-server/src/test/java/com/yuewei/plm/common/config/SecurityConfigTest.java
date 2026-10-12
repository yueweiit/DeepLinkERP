package com.yuewei.plm.common.config;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.security.SimpleTokenAuthenticationFilter;
import org.junit.jupiter.api.Test;
import org.springframework.boot.web.servlet.FilterRegistrationBean;

class SecurityConfigTest {

    @Test
    void simpleTokenAuthenticationFilterIsNotAutoRegisteredAsServletFilter() {
        SimpleTokenAuthenticationFilter filter = mock(SimpleTokenAuthenticationFilter.class);
        SecurityConfig config = new SecurityConfig(filter, new ObjectMapper(), new AppProperties());

        FilterRegistrationBean<SimpleTokenAuthenticationFilter> registration =
            config.simpleTokenAuthenticationFilterRegistration(filter);

        assertThat(registration.getFilter()).isSameAs(filter);
        assertThat(registration.isEnabled()).isFalse();
    }
}
