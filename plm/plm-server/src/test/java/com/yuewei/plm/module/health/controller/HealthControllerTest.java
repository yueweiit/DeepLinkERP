package com.yuewei.plm.module.health.controller;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.yuewei.plm.common.exception.GlobalExceptionHandler;
import javax.sql.DataSource;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.core.env.Environment;
import org.springframework.http.MediaType;
import org.springframework.validation.beanvalidation.LocalValidatorFactoryBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class HealthControllerTest {

    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        DataSource dataSource = mock(DataSource.class);
        Environment environment = mock(Environment.class);
        when(environment.getActiveProfiles()).thenReturn(new String[] {"dev"});

        LocalValidatorFactoryBean validator = new LocalValidatorFactoryBean();
        validator.afterPropertiesSet();

        mockMvc = MockMvcBuilders
            .standaloneSetup(new HealthController(dataSource, environment, "plm-server"))
            .setControllerAdvice(new GlobalExceptionHandler())
            .setValidator(validator)
            .build();
    }

    @Test
    void healthReturnsUpStatus() throws Exception {
        mockMvc.perform(get("/api/v1/health"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.code").value(0))
            .andExpect(jsonPath("$.data.status").value("UP"));
    }

    @Test
    void validationProbeRejectsBlankName() throws Exception {
        mockMvc.perform(post("/api/v1/health/validation-probe")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"name\":\"\"}"))
            .andExpect(status().isBadRequest())
            .andExpect(jsonPath("$.code").value(40001));
    }

    @Test
    void validationProbeAcceptsValidName() throws Exception {
        mockMvc.perform(post("/api/v1/health/validation-probe")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"name\":\"skeleton\"}"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.code").value(0))
            .andExpect(jsonPath("$.data").value("skeleton"));
    }
}
