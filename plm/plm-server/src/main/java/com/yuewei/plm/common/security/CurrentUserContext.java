package com.yuewei.plm.common.security;

import java.util.Optional;

public final class CurrentUserContext {

    private static final ThreadLocal<CurrentUser> CURRENT = new ThreadLocal<>();

    private CurrentUserContext() {
    }

    public static void set(CurrentUser currentUser) {
        CURRENT.set(currentUser);
    }

    public static Optional<CurrentUser> get() {
        return Optional.ofNullable(CURRENT.get());
    }

    public static void clear() {
        CURRENT.remove();
    }
}
