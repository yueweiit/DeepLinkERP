package com.yuewei.plm.module.marketwatch;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.sun.net.httpserver.HttpServer;
import com.yuewei.plm.common.config.AppProperties;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class MarketWatchClientTest {
    private HttpServer server;
    private final AtomicReference<String> authorization = new AtomicReference<>();

    @BeforeEach
    void startServer() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.start();
    }

    @AfterEach
    void stopServer() {
        server.stop(0);
    }

    @Test
    void forwardsOnlyTheServerTokenAndParsesAHealthyResponse() {
        server.createContext("/internal/v1/health", exchange -> {
            authorization.set(exchange.getRequestHeaders().getFirst("Authorization"));
            byte[] body = "{\"status\":\"ok\"}".getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });

        MarketWatchClient client = client("service-secret");
        assertThat(client.health()).containsEntry("status", "ok");
        assertThat(authorization).hasValue("Bearer service-secret");
    }

    @Test
    void hidesUpstreamBodiesAndCredentialsFromFailures() {
        server.createContext("/internal/v1/summary", exchange -> {
            byte[] body = "production database password: leaked-value".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(500, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });

        assertThatThrownBy(() -> client("service-secret").summary())
            .isInstanceOfSatisfying(BusinessException.class, error -> {
                assertThat(error.getCode()).isEqualTo(ErrorCodeConstants.UPSTREAM_UNAVAILABLE);
                assertThat(error.getMessage()).doesNotContain("leaked-value", "service-secret");
            });
    }

    private MarketWatchClient client(String token) {
        AppProperties properties = new AppProperties();
        properties.getPhoneWatch().setEnabled(true);
        properties.getPhoneWatch().setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
        properties.getPhoneWatch().setToken(token);
        properties.getPhoneWatch().setConnectTimeoutMs(250);
        properties.getPhoneWatch().setReadTimeoutMs(500);
        return new MarketWatchClient(properties);
    }
}
