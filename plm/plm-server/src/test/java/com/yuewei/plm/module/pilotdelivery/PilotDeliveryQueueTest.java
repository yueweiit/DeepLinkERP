package com.yuewei.plm.module.pilotdelivery;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import com.yuewei.plm.module.pilot.PilotAccessService;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.env.MockEnvironment;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.mock;

class PilotDeliveryQueueTest {
    final ObjectMapper json=new ObjectMapper().findAndRegisterModules();
    static class Source extends JdbcTemplate {
        final List<String> sqls=new ArrayList<>();final List<Object[]> updates=new ArrayList<>();boolean same=true,claimed;
        @Override public int update(String sql){return update(sql,new Object[]{});}
        @Override public int update(String sql,Object...args){sqls.add(sql);updates.add(args);return 1;}
        @Override public <T>T queryForObject(String sql,Class<T> type,Object...args){return type.cast(type==Boolean.class?same:1L);}
        @Override public List<Map<String,Object>> queryForList(String sql){return queryForList(sql,new Object[]{});}
        @Override public List<Map<String,Object>> queryForList(String sql,Object...args){sqls.add(sql);if(claimed)return List.of();claimed=true;return List.of(Map.of("task_id",1L,"kind","erp_bom","event_id","event-1","payload","{\"bomId\":7}","attempts",1,"lease_token","fixture-lease"));}
        String finished(){return updates.stream().filter(a->a.length>0&&Set.of("failed","succeeded","not_configured").contains(Objects.toString(a[0]))).map(a->a[0].toString()).reduce((a,b)->b).orElse(null);}
    }
    @Test void sameEventUsesStableDeduplicationAndChangedPayloadIsRejected() {
        var source=new Source();var queue=new PilotDeliveryQueue(source,json,new MockEnvironment(),mock(PilotAccessService.class));assertThat(queue.enqueue("erp_bom","stable-1",Map.of("bomId",7),19)).isEqualTo("stable-1");assertThat(queue.enqueue("erp_bom","stable-1",Map.of("bomId",7),19)).isEqualTo("stable-1");assertThat(source.sqls).anyMatch(sql->sql.contains("on conflict(event_id) do nothing"));source.same=false;assertThatThrownBy(()->queue.enqueue("erp_bom","stable-1",Map.of("bomId",8),19)).hasMessageContaining("改变");
    }
    @Test void disabledAndNotConfiguredNeverSendAnyRequests() {
        var source=new Source();var env=new MockEnvironment();var queue=new PilotDeliveryQueue(source,json,env,mock(PilotAccessService.class));queue.dispatchPending();assertThat(source.sqls).isEmpty();env.setProperty("PLM_PILOT_DELIVERY_ENABLED","true");queue.dispatchPending();assertThat(source.finished()).isEqualTo("not_configured");assertThat(source.sqls).anyMatch(sql->sql.contains("skip locked"));
    }
    @Test void onlyMatchingBusinessReceiptCompletesTheEventAndResponseSecretsAreNotPersisted()throws Exception {
        HttpServer server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);AtomicInteger posts=new AtomicInteger();server.createContext("/delivery",exchange->{posts.incrementAndGet();assertThat(exchange.getRequestMethod()).isEqualTo("POST");assertThat(exchange.getRequestHeaders().getFirst("Idempotency-Key")).isEqualTo("event-1");byte[] reply="{\"message\":{\"eventId\":\"event-1\",\"status\":\"duplicate\",\"secret\":\"must-not-store\"}}".getBytes(StandardCharsets.UTF_8);exchange.getRequestBody().readAllBytes();exchange.sendResponseHeaders(200,reply.length);exchange.getResponseBody().write(reply);exchange.close();});server.start();try {var source=new Source();var env=config(server);var queue=new PilotDeliveryQueue(source,json,env,mock(PilotAccessService.class));queue.dispatchPending();assertThat(posts).hasValue(1);assertThat(source.finished()).isEqualTo("succeeded");assertThat(source.updates.stream().flatMap(a->Arrays.stream(a)).map(Objects::toString)).noneMatch(v->v.contains("must-not-store"));}finally{server.stop(0);}
    }
    @Test void mismatchedAcknowledgementKeepsFailureRetryableWithoutReportingSuccess()throws Exception {
        HttpServer server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);server.createContext("/delivery",exchange->{byte[] reply="{\"message\":{\"eventId\":\"wrong\",\"status\":\"accepted\"}}".getBytes(StandardCharsets.UTF_8);exchange.getRequestBody().readAllBytes();exchange.sendResponseHeaders(200,reply.length);exchange.getResponseBody().write(reply);exchange.close();});server.start();try{var source=new Source();new PilotDeliveryQueue(source,json,config(server),mock(PilotAccessService.class)).dispatchPending();assertThat(source.finished()).isEqualTo("failed");assertThat(source.sqls).anyMatch(s->s.contains("available_at"));}finally{server.stop(0);}
    }
    private MockEnvironment config(HttpServer server){return new MockEnvironment().withProperty("PLM_PILOT_DELIVERY_ENABLED","true").withProperty("PLM_PILOT_ERP_URL","http://127.0.0.1:"+server.getAddress().getPort()+"/delivery").withProperty("PLM_PILOT_ERP_TOKEN","test-only-token");}
}
