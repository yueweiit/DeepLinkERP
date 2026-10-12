package com.yuewei.plm.module.auth.service;

import com.yuewei.plm.common.security.CurrentUser;
import java.util.Optional;

public interface TokenSessionService {

    String createSession(CurrentUser currentUser);

    Optional<CurrentUser> getCurrentUser(String token);

    void invalidate(String token);

    long getExpiresInSeconds();
}
