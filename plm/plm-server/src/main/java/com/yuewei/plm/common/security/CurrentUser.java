package com.yuewei.plm.common.security;

public record CurrentUser(
    Long userId,
    String username,
    String displayName,
    boolean allPermissions
) {
}
