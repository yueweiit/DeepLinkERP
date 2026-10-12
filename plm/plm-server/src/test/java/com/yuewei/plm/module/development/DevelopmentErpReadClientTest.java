package com.yuewei.plm.module.development;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

class DevelopmentErpReadClientTest {
    final ObjectMapper json=new ObjectMapper().findAndRegisterModules();
    @Test void unconfiguredAndUnsafeEndpointsNeverOpenExternalRequests(){var missing=new DevelopmentErpReadClient("","",json);assertThat(missing.configured()).isFalse();assertThatThrownBy(missing::read).hasMessageContaining("未配置");var plain=new DevelopmentErpReadClient("http://example.invalid/erp","unit-test-token",json);assertThatThrownBy(plain::read).hasMessageContaining("HTTPS");var query=new DevelopmentErpReadClient("https://example.invalid/erp?token=bad","unit-test-token",json);assertThatThrownBy(query::read).hasMessageContaining("HTTPS");}
    @Test void readsOnlyGetAndPreservesStableIdsCurrencyAndSignedReversal()throws Exception {
        HttpServer server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);AtomicInteger calls=new AtomicInteger();server.createContext("/rows",exchange->{calls.incrementAndGet();assertThat(exchange.getRequestMethod()).isEqualTo("GET");assertThat(exchange.getRequestHeaders().getFirst("Authorization")).isEqualTo("Bearer unit-test-token");byte[] body="{\"rows\":[{\"voucherId\":\"GL1\",\"lineId\":\"ROW1\",\"description\":\"冲销\",\"currency\":\"CNY\",\"postedAmount\":-100,\"docstatus\":1,\"reversalOf\":\"GL0/ROW0\"}]}".getBytes(StandardCharsets.UTF_8);exchange.sendResponseHeaders(200,body.length);exchange.getResponseBody().write(body);exchange.close();});server.start();try {var client=new DevelopmentErpReadClient("http://127.0.0.1:"+server.getAddress().getPort()+"/rows","unit-test-token",json);assertThat(client.read()).singleElement().satisfies(row->{assertThat(row.lineId()).isEqualTo("ROW1");assertThat(row.postedAmount()).isEqualByComparingTo("-100");assertThat(row.reversalOf()).isEqualTo("GL0/ROW0");});assertThat(calls).hasValue(1);}finally{server.stop(0);}
    }
    @Test void refusesRedirectsInsteadOfForwardingAuthentication()throws Exception {
        HttpServer server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);AtomicInteger redirected=new AtomicInteger();server.createContext("/redirect",exchange->{exchange.getResponseHeaders().add("Location","/target");exchange.sendResponseHeaders(302,-1);exchange.close();});server.createContext("/target",exchange->{redirected.incrementAndGet();exchange.sendResponseHeaders(200,-1);exchange.close();});server.start();try{var client=new DevelopmentErpReadClient("http://127.0.0.1:"+server.getAddress().getPort()+"/redirect","unit-test-token",json);assertThatThrownBy(client::read).hasMessageContaining("只读请求失败");assertThat(redirected).hasValue(0);}finally{server.stop(0);}
    }
    @Test void rejectsUnpostedOrOversizedResponsesBeforeAnyCommit()throws Exception {
        HttpServer server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);server.createContext("/unposted",exchange->{byte[] body="{\"rows\":[{\"voucherId\":\"GL1\",\"lineId\":\"ROW1\",\"description\":\"draft\",\"currency\":\"USD\",\"postedAmount\":100,\"docstatus\":0}]}".getBytes(StandardCharsets.UTF_8);exchange.sendResponseHeaders(200,body.length);exchange.getResponseBody().write(body);exchange.close();});server.createContext("/large",exchange->{byte[] body=new byte[2*1024*1024+1];exchange.sendResponseHeaders(200,body.length);try{exchange.getResponseBody().write(body);}catch(java.io.IOException ignored){}exchange.close();});server.start();try{String base="http://127.0.0.1:"+server.getAddress().getPort();assertThatThrownBy(()->new DevelopmentErpReadClient(base+"/unposted","unit-test-token",json).read()).hasMessageContaining("未过账");assertThatThrownBy(()->new DevelopmentErpReadClient(base+"/large","unit-test-token",json).read()).hasMessageContaining("响应校验");}finally{server.stop(0);}
    }
}
