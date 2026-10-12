package com.yuewei.plm.module.pilotdelivery;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.module.pilot.PilotAccessService;
import com.yuewei.plm.infrastructure.http.SafeHttpTransport;
import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.*;
import lombok.RequiredArgsConstructor;
import org.springframework.core.env.Environment;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

/** Immutable source snapshots plus at-least-once deliveries; never a second BOM workflow. */
@Service
@RequiredArgsConstructor
public class PilotDeliveryQueue {
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    private final Environment env;
    private final PilotAccessService access;
    private final HttpClient http=SafeHttpTransport.client();
    public String enqueue(String kind,String eventId,Object payload,long actorId) {
        String encoded=encode(payload);
        jdbc.update("insert into plm_pilot_delivery_task(kind,event_id,payload,actor_id) values(?,?,?::jsonb,?) on conflict(event_id) do nothing",kind,eventId,encoded,actorId);
        Boolean same=jdbc.queryForObject("select kind=? and payload=?::jsonb from plm_pilot_delivery_task where event_id=?",Boolean.class,kind,encoded,eventId);
        if(!Boolean.TRUE.equals(same)) throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR,"相同事件内容已改变，请创建新的业务版本");
        return eventId;
    }
    public Map<String,Object> configuration() {
        access.requirePermission("pilot:admin");
        return Map.of("enabled",enabled(),"erpConfigured",configured("erp_bom"),"erpExpensesConfigured",expenseConfigured(),"dingtalkConfigured",configured("dingtalk_reminder"),
            "message","凭据仅来自运行环境；未配置不发送，未取得匹配事件回执不标记成功");
    }
    public Map<String,Object> page(int page,int size,String status) {
        access.requirePermission("pilot:admin");page=Math.max(1,page);size=Math.max(1,Math.min(100,size));
        String where=status==null||status.isBlank()?"true":"status=?";
        List<Object> args=new ArrayList<>();if(!where.equals("true"))args.add(status);
        Long count=jdbc.queryForObject("select count(*) from plm_pilot_delivery_task where "+where,Long.class,args.toArray());
        args.add(size);args.add((page-1)*size);
        var rows=jdbc.queryForList("select task_id,kind,event_id,status,attempts,last_error,receipt,created_at,updated_at from plm_pilot_delivery_task where "+where+" order by task_id desc limit ? offset ?",args.toArray());
        return Map.of("content",rows,"page",page,"size",size,"totalElements",count,"totalPages",(count+size-1)/size);
    }
    public void retry(long id) {
        access.requirePermission("pilot:admin");
        int n=jdbc.update("update plm_pilot_delivery_task set status='pending',available_at=now(),last_error=null,updated_at=now() where task_id=? and status in ('failed','not_configured')",id);
        if(n==0)throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR,"只可重试失败或未配置的任务，成功任务不能重复发送");
    }
    public boolean enabled(){return env.getProperty("PLM_PILOT_DELIVERY_ENABLED",Boolean.class,false);}
    boolean configured(String kind){return endpoint(kind)!=null&&!token(kind).isBlank();}
    boolean expenseConfigured(){try {return !env.getProperty("PLM_PILOT_ERP_EXPENSES_TOKEN","").isBlank()&&SafeHttpTransport.endpoint(env.getProperty("PLM_PILOT_ERP_EXPENSES_URL","")).getHost()!=null;}catch(IllegalArgumentException e){return false;}}
    private String propertyPrefix(String kind){return switch(kind){case "erp_bom"->"PLM_PILOT_ERP";case "dingtalk_reminder"->"PLM_PILOT_DINGTALK";default->throw new IllegalArgumentException("Unsupported delivery kind");};}
    private URI endpoint(String kind) {
        String raw=env.getProperty(propertyPrefix(kind)+"_URL","");if(raw.isBlank())return null;
        try {return SafeHttpTransport.endpoint(raw);}catch(IllegalArgumentException e){return null;}
    }
    private String token(String kind){return env.getProperty(propertyPrefix(kind)+"_TOKEN","");}
    @Scheduled(fixedDelayString="${app.pilot.delivery-delay-ms:30000}")
    public void dispatchPending() {
        if(!enabled())return;
        bridgeReminders();
        // PostgreSQL lease is shared across workers and survives process restart.
        for(int n=0;n<10;n++){var rows=jdbc.queryForList("update plm_pilot_delivery_task set status='sending',lease_until=now()+interval '60 seconds',attempts=attempts+1,updated_at=now() where task_id in (select task_id from plm_pilot_delivery_task where (status in ('pending','failed') and available_at<=now()) or (status='sending' and lease_until<now()) order by task_id for update skip locked limit 1) returning task_id,kind,event_id,payload,attempts");if(rows.isEmpty())break;send(rows.get(0));}
    }
    /** Group only not-yet-dispatched station reminders; one immutable batch per recipient. */
    void bridgeReminders(){jdbc.update("""
        with eligible as (
          select r.*,a.dingtalk_user_id,creator.user_id creator_id from plm_mold_schedule_reminder r
          join sys_user u on u.user_id=r.recipient_id and u.deleted_flag=0 and u.status='active'
          join plm_pilot_account a on a.user_id=u.user_id and a.dingtalk_user_id is not null
          left join sys_user creator on creator.username=r.created_by
          where r.status='pending' and r.delivery_event_id is null order by r.reminder_id limit 1000
        ), batches as (
          select recipient_id,'schedule-reminders:'||recipient_id||':'||min(reminder_id)||'-'||max(reminder_id) event_id,
            jsonb_build_object('recipientUserId',recipient_id,'dingtalkUserId',dingtalk_user_id,
              'reminderIds',jsonb_agg(reminder_id order by reminder_id),'tasks',jsonb_agg(payload order by reminder_id)) payload,
            min(creator_id) actor_id from eligible group by recipient_id,dingtalk_user_id
        ), inserted as (
          insert into plm_pilot_delivery_task(kind,event_id,payload,actor_id)
            select 'dingtalk_reminder',event_id,payload,actor_id from batches on conflict(event_id) do nothing returning event_id,payload
        ) update plm_mold_schedule_reminder r set delivery_event_id=i.event_id from inserted i
          where i.payload->'reminderIds' @> jsonb_build_array(r.reminder_id)
        """);}
    private void send(Map<String,Object> row) {
        long id=((Number)row.get("task_id")).longValue();int attempt=((Number)row.get("attempts")).intValue();String kind=row.get("kind").toString(),event=row.get("event_id").toString();
        if(!configured(kind)){finish(id,attempt,"not_configured","接入地址或运行凭据未配置",null,0);return;}
        try {
            var payload=json.createObjectNode();payload.put("eventId",event);payload.put("kind",kind);payload.set("data",json.readTree(row.get("payload").toString()));
            var request=HttpRequest.newBuilder(endpoint(kind)).timeout(Duration.ofSeconds(10)).header("Authorization","Bearer "+token(kind))
                .header("Content-Type","application/json").header("Idempotency-Key",event).POST(HttpRequest.BodyPublishers.ofString(encode(payload))).build();
            var response=http.send(request,SafeHttpTransport.boundedBody(65536));
            if(response.statusCode()!=200&&response.statusCode()!=201)throw new IllegalStateException("HTTP "+response.statusCode());JsonNode body=json.readTree(response.body());
            JsonNode receipt=body.has("message")?body.get("message"):body;
            if(!event.equals(receipt.path("eventId").asText())||!Set.of("created","duplicate","accepted").contains(receipt.path("status").asText()))throw new IllegalStateException("业务回执不匹配");
            // Do not persist an arbitrary remote body which may contain credentials or personal data.
            finish(id,attempt,"succeeded",null,encode(Map.of("eventId",event,"status",receipt.path("status").asText())),0);
        }catch(Exception e){if(e instanceof InterruptedException)Thread.currentThread().interrupt();
            int seconds=Math.min(3600,30*(1<<Math.min(7,((Number)row.get("attempts")).intValue())));
            finish(id,attempt,"failed",e instanceof IllegalStateException?e.getMessage():e.getClass().getSimpleName(),null,seconds);
        }
    }
    private void finish(long id,int attempt,String status,String error,String receipt,int seconds){jdbc.update("update plm_pilot_delivery_task set status=?,last_error=?,receipt=?::jsonb,lease_until=null,available_at=now()+make_interval(secs=>?),updated_at=now() where task_id=? and status='sending' and attempts=?",status,error,receipt,seconds,id,attempt);}
    String encode(Object value){try{return json.writeValueAsString(value);}catch(Exception e){throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR,"同步载荷无法编码");}}
}
