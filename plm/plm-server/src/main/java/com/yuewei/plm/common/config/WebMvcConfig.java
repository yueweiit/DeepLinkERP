package com.yuewei.plm.common.config;

import com.yuewei.plm.common.interceptor.RequestLoggingInterceptor;
import java.nio.charset.StandardCharsets;
import java.util.List;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.MediaType;
import org.springframework.http.converter.HttpMessageConverter;
import org.springframework.http.converter.StringHttpMessageConverter;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class WebMvcConfig implements WebMvcConfigurer {

    private final RequestLoggingInterceptor requestLoggingInterceptor;

    @Autowired
    public WebMvcConfig(RequestLoggingInterceptor requestLoggingInterceptor) {
        this.requestLoggingInterceptor = requestLoggingInterceptor;
    }

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(requestLoggingInterceptor).addPathPatterns("/api/**");
    }

    @Override
    public void extendMessageConverters(List<HttpMessageConverter<?>> converters) {
        MediaType jsonUtf8 = new MediaType("application", "json", StandardCharsets.UTF_8);
        for (HttpMessageConverter<?> converter : converters) {
            if (converter instanceof MappingJackson2HttpMessageConverter jacksonConverter) {
                jacksonConverter.setDefaultCharset(StandardCharsets.UTF_8);
                jacksonConverter.setSupportedMediaTypes(List.of(
                    jsonUtf8,
                    MediaType.APPLICATION_JSON,
                    new MediaType("application", "*+json", StandardCharsets.UTF_8),
                    MediaType.APPLICATION_PROBLEM_JSON
                ));
            }
            if (converter instanceof StringHttpMessageConverter stringConverter) {
                stringConverter.setDefaultCharset(StandardCharsets.UTF_8);
            }
        }
    }
}
