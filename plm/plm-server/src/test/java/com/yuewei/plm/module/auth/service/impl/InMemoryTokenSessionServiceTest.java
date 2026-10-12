package com.yuewei.plm.module.auth.service.impl;

import static org.assertj.core.api.Assertions.assertThat;

import com.yuewei.plm.common.security.CurrentUser;
import org.junit.jupiter.api.Test;

class InMemoryTokenSessionServiceTest {

    @Test
    void createSessionReturnsRetrievableCurrentUserAndInvalidateRemovesIt() {
        InMemoryTokenSessionService service = new InMemoryTokenSessionService();
        CurrentUser user = new CurrentUser(1L, "engineer01", "工程部用户一", true);

        String token = service.createSession(user);

        assertThat(token).isNotBlank();
        assertThat(service.getCurrentUser(token)).contains(user);

        service.invalidate(token);

        assertThat(service.getCurrentUser(token)).isEmpty();
    }
}
