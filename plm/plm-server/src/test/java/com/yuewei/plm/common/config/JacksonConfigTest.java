package com.yuewei.plm.common.config;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.vo.ResponseVO;
import java.time.OffsetDateTime;
import org.junit.jupiter.api.Test;

class JacksonConfigTest {

    @Test
    void objectMapperSerializesOffsetDateTimeAsIsoString() throws Exception {
        ObjectMapper objectMapper = new JacksonConfig().objectMapper();
        ResponseVO<String> response = ResponseVO.success(
            "ok",
            "req-1",
            OffsetDateTime.parse("2026-07-02T10:00:00+08:00")
        );

        String json = objectMapper.writeValueAsString(response);

        assertThat(json).contains("\"timestamp\":\"2026-07-02T10:00:00+08:00\"");
    }
}
