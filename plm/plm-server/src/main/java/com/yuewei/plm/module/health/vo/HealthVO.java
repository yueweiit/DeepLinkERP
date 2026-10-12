package com.yuewei.plm.module.health.vo;

import java.time.OffsetDateTime;

public record HealthVO(
    String status,
    String application,
    String profile,
    String database,
    OffsetDateTime timestamp
) {
}
