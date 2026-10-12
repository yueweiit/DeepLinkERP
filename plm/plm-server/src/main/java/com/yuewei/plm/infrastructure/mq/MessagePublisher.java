package com.yuewei.plm.infrastructure.mq;

import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

@Slf4j
@Component
public class MessagePublisher {

    public void publish(String topic, Object payload) {
        log.debug("Publish message to topic={}, payload={}", topic, payload);
    }
}
