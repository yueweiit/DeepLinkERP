package com.yuewei.plm.infrastructure.sse;

import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

@Slf4j
@Component
public class SseBroadcaster {

    public void broadcast(String eventName, Object payload) {
        log.debug("SSE event broadcast: {}, payload={}", eventName, payload);
    }
}
