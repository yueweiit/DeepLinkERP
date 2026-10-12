package com.yuewei.plm.module.auth.service.impl;

import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.module.auth.service.TokenSessionService;
import java.security.SecureRandom;
import java.time.Instant;
import java.util.Base64;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

@Service
public class InMemoryTokenSessionService implements TokenSessionService {

    private static final long EXPIRES_IN_SECONDS = 8 * 60 * 60;
    // M1 先使用单实例内存会话；多实例部署前需要替换为 Redis 等共享会话存储。
    private final ConcurrentHashMap<String, TokenSession> sessions = new ConcurrentHashMap<>();
    private final SecureRandom secureRandom = new SecureRandom();

    @Override
    public String createSession(CurrentUser currentUser) {
        byte[] bytes = new byte[32];
        secureRandom.nextBytes(bytes);
        String token = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
        sessions.put(token, new TokenSession(currentUser, Instant.now().plusSeconds(EXPIRES_IN_SECONDS)));
        return token;
    }

    @Override
    public Optional<CurrentUser> getCurrentUser(String token) {
        if (!StringUtils.hasText(token)) {
            return Optional.empty();
        }
        TokenSession session = sessions.get(token);
        if (session == null) {
            return Optional.empty();
        }
        if (session.expiresAt().isBefore(Instant.now())) {
            sessions.remove(token);
            return Optional.empty();
        }
        return Optional.of(session.currentUser());
    }

    @Override
    public void invalidate(String token) {
        if (StringUtils.hasText(token)) {
            sessions.remove(token);
        }
    }

    @Override
    public long getExpiresInSeconds() {
        return EXPIRES_IN_SECONDS;
    }

    private record TokenSession(CurrentUser currentUser, Instant expiresAt) {
    }
}
