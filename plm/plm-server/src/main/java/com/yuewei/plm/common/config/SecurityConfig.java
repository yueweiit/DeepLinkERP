package com.yuewei.plm.common.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.security.SimpleTokenAuthenticationFilter;
import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import java.time.OffsetDateTime;
import jakarta.servlet.http.HttpServletResponse;
import java.util.List;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;

@Configuration
public class SecurityConfig {

    private final SimpleTokenAuthenticationFilter simpleTokenAuthenticationFilter;
    private final ObjectMapper objectMapper;
    private final AppProperties appProperties;

    public SecurityConfig(SimpleTokenAuthenticationFilter simpleTokenAuthenticationFilter,
                          ObjectMapper objectMapper,
                          AppProperties appProperties) {
        this.simpleTokenAuthenticationFilter = simpleTokenAuthenticationFilter;
        this.objectMapper = objectMapper;
        this.appProperties = appProperties;
    }

    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        http.cors(cors -> cors.configurationSource(corsConfigurationSource()))
            .csrf(csrf -> csrf.disable())
            .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .authorizeHttpRequests(auth -> {
                auth.requestMatchers(HttpMethod.OPTIONS, "/**").permitAll()
                    .requestMatchers(
                        "/api/v1/health/**",
                        "/api/v1/auth/login",
                        "/api/v1/pilot/dingtalk/login",
                        "/api/v1/pilot/dingtalk/status",
                        "/api/v1/integrations/dingtalk/approval-callbacks",
                        "/api/v1/integrations/dingtalk/outbound",
                        "/api/dingtalk/outbound",
                        "/swagger-ui.html",
                        "/swagger-ui/**",
                        "/v3/api-docs/**"
                    ).permitAll();
                if (!appProperties.getSecurity().isEnabled()) {
                    auth.requestMatchers("/api/v1/**").permitAll();
                } else {
                    auth.requestMatchers("/api/v1/**").authenticated();
                }
                auth.anyRequest().permitAll();
            })
            .exceptionHandling(exception -> exception.authenticationEntryPoint((request, response, authException) -> {
                response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
                response.setContentType("application/json;charset=UTF-8");
                objectMapper.writeValue(response.getWriter(), ResponseVO.error(
                    ErrorCodeConstants.UNAUTHORIZED,
                    "未登录或登录已失效",
                    RequestIdUtil.getRequestId(request),
                    OffsetDateTime.now()
                ));
            }))
            .addFilterBefore(simpleTokenAuthenticationFilter, UsernamePasswordAuthenticationFilter.class);
        return http.build();
    }

    @Bean
    public FilterRegistrationBean<SimpleTokenAuthenticationFilter> simpleTokenAuthenticationFilterRegistration(
            SimpleTokenAuthenticationFilter filter) {
        FilterRegistrationBean<SimpleTokenAuthenticationFilter> registration = new FilterRegistrationBean<>(filter);
        registration.setEnabled(false);
        return registration;
    }

    @Bean
    public CorsConfigurationSource corsConfigurationSource() {
        CorsConfiguration configuration = new CorsConfiguration();
        configuration.setAllowedOriginPatterns(List.of(
            "http://localhost:*",
            "http://127.0.0.1:*"
        ));
        configuration.setAllowedMethods(List.of("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"));
        configuration.setAllowedHeaders(List.of(
            "Authorization",
            "Content-Type",
            "X-Request-Id",
            "Accept",
            "Origin"
        ));
        configuration.setExposedHeaders(List.of("X-Request-Id"));
        configuration.setAllowCredentials(true);
        configuration.setMaxAge(3600L);

        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", configuration);
        return source;
    }

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }
}
