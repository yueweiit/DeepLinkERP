package com.yuewei.plm.module.pilot;
import lombok.RequiredArgsConstructor;import org.springframework.context.annotation.Configuration;import org.springframework.web.servlet.config.annotation.*;
@Configuration @RequiredArgsConstructor
public class PilotWebConfig implements WebMvcConfigurer {
 private final PilotSecurityInterceptor security;
 @Override public void addInterceptors(InterceptorRegistry registry){registry.addInterceptor(security).addPathPatterns("/api/v1/**").order(-100);}
}
