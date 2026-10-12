package com.yuewei.plm.common.vo;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.OffsetDateTime;
import org.junit.jupiter.api.Test;

class ResponseVOTest {

    @Test
    void successWrapsDataWithRequestMetadata() {
        OffsetDateTime now = OffsetDateTime.parse("2026-07-02T10:00:00+08:00");

        ResponseVO<String> response = ResponseVO.success("ok", "req-1", now);

        assertThat(response.getCode()).isZero();
        assertThat(response.getMessage()).isEqualTo("success");
        assertThat(response.getData()).isEqualTo("ok");
        assertThat(response.getRequestId()).isEqualTo("req-1");
        assertThat(response.getTimestamp()).isEqualTo(now);
    }

    @Test
    void errorWrapsCodeMessageAndRequestMetadata() {
        OffsetDateTime now = OffsetDateTime.parse("2026-07-02T10:00:00+08:00");

        ResponseVO<Void> response = ResponseVO.error(40001, "参数校验失败", "req-2", now);

        assertThat(response.getCode()).isEqualTo(40001);
        assertThat(response.getMessage()).isEqualTo("参数校验失败");
        assertThat(response.getData()).isNull();
        assertThat(response.getRequestId()).isEqualTo("req-2");
        assertThat(response.getTimestamp()).isEqualTo(now);
    }
}
