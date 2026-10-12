package com.yuewei.plm.module.marketwatch;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.common.security.CurrentUserContext;
import com.yuewei.plm.module.collaboration.CollaborationService;
import com.yuewei.plm.module.collaboration.CollaborationTypes.CreateItem;
import com.yuewei.plm.module.marketwatch.MarketWatchTypes.BulkUpdate;
import com.yuewei.plm.module.marketwatch.MarketWatchTypes.Promote;
import com.yuewei.plm.module.marketwatch.MarketWatchTypes.UpdateItem;
import jakarta.servlet.http.HttpServletRequest;
import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;

@Service
@RequiredArgsConstructor
public class MarketWatchService {
    private final MarketWatchClient client;
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    private final CollaborationService collaboration;
    private final org.springframework.transaction.PlatformTransactionManager transactionManager;

    public Map<String,Object> config() {
        CurrentUser actor = actor();
        return Map.of("enabled",client.enabled(),"writable",canWrite(actor),"administrator",actor.allPermissions());
    }

    public Map<String,Object> health() { readGate(); return client.health(); }
    public Map<String,Object> summary() { readGate(); return client.summary(); }
    @SuppressWarnings("unchecked")
    public Map<String,Object> items(MultiValueMap<String,String> query) {
        readGate();
        Map<String,Object> page=new LinkedHashMap<>(client.items(query));
        Object rawContent=page.get("content");
        if(!(rawContent instanceof List<?> values)||values.isEmpty()) return page;
        List<Map<String,Object>> content=values.stream().filter(Map.class::isInstance)
            .map(value->(Map<String,Object>)new LinkedHashMap<>((Map<String,Object>)value)).toList();
        String kind=Objects.toString(content.get(0).get("kind"),"");
        List<Long> ids=content.stream().map(item->((Number)item.get("id")).longValue()).toList();
        String placeholders=String.join(",",java.util.Collections.nCopies(ids.size(),"?"));
        List<Object> params=new java.util.ArrayList<>();params.add(kind);params.addAll(ids);
        Map<Long,Map<String,Object>> links=new LinkedHashMap<>();
        for(Map<String,Object> row:jdbc.queryForList("""
            select source_kind as "sourceKind",source_id as "sourceId",collaboration_item_id as "itemId",
                   promoted_by_id as "promotedById",promoted_by_name as "promotedByName",promoted_at as "promotedAt"
              from plm_market_watch_link where source_kind=? and source_id in (%s)
            """.formatted(placeholders),params.toArray())) links.put(((Number)row.get("sourceId")).longValue(),row);
        content.forEach(item->item.put("collaborationLink",links.get(((Number)item.get("id")).longValue())));
        page.put("content",content);
        return page;
    }

    public Map<String,Object> detail(String kind,long id) {
        readGate();
        Map<String,Object> item = new LinkedHashMap<>(client.detail(kind,id));
        link(kind,id).ifPresent(link -> item.put("collaborationLink",link));
        return item;
    }

    public Map<String,Object> update(String kind,long id,UpdateItem update) {
        writeGate();
        Map<String,Object> payload = new LinkedHashMap<>();
        if (update.status()!=null) payload.put("status",update.status());
        if (update.badge()!=null) payload.put("badge",update.badge());
        if (update.saleStatus()!=null) payload.put("saleStatus",update.saleStatus());
        return client.update(kind,id,payload);
    }

    public Map<String,Object> bulk(BulkUpdate update) {
        writeGate();
        Map<String,Object> payload = new LinkedHashMap<>();
        payload.put("kind",update.kind());payload.put("ids",update.ids());
        if (update.status()!=null) payload.put("status",update.status());
        if (update.badge()!=null) payload.put("badge",update.badge());
        if (update.saleStatus()!=null) payload.put("saleStatus",update.saleStatus());
        return client.bulk(payload);
    }

    public MarketWatchClient.CsvFile export(MultiValueMap<String,String> query) { readGate(); return client.export(query); }

    public Map<String,Object> promotionOptions(String kind,long id) {
        readGate();
        Map<String,Object> source = client.detail(kind,id);
        List<Map<String,Object>> matches = jdbc.queryForList("""
            select item_id as "itemId",product_line_id as "productLineId",style_name as "styleName",
                   brand,compatible_models as "compatibleModels",phone_model_code as "phoneModelCode"
              from plm_collaboration_item
             where deleted_flag=0 and lower(btrim(compatible_models))=lower(btrim(?))
             order by updated_at desc,item_id desc limit 20
            """,text(source,"model"));
        Map<String,Object> result = new LinkedHashMap<>();
        result.put("source",source);result.put("matches",matches);
        result.put("link",link(kind,id).orElse(null));
        return result;
    }

    public Map<String,Object> promote(Promote command,HttpServletRequest request) {
        CurrentUser actor = writeGate();
        Map<String,Object> source = client.detail(command.sourceKind(),command.sourceId());
        return Objects.requireNonNull(new TransactionTemplate(transactionManager).execute(status -> {
            jdbc.queryForObject("select pg_advisory_xact_lock(hashtextextended(?,610091200))",(rs,rowNum)->true,
                command.sourceKind()+":"+command.sourceId());
            var existing = link(command.sourceKind(),command.sourceId());
            if (existing.isPresent()) return promotionResult(existing.get(),true);

            long itemId;
            if ("link".equals(command.mode())) {
                if (command.itemId()==null) throw invalid("关联已有档案时必须选择协作计划档案");
                Long count=jdbc.queryForObject("select count(*) from plm_collaboration_item where item_id=? and deleted_flag=0",Long.class,command.itemId());
                if(count==null||count==0) throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND,"协作计划档案不存在");
                itemId=command.itemId();
            } else {
                if(command.productLineId()==null) throw invalid("新建档案必须人工确认产品线");
                if(blank(command.styleName())) throw invalid("新建档案必须人工确认产品款式");
                String models=blank(command.compatibleModels())?text(source,"model"):command.compatibleModels().trim();
                List<Map<String,Object>> duplicate=jdbc.queryForList("""
                    select item_id as "itemId",style_name as "styleName",compatible_models as "compatibleModels"
                    from plm_collaboration_item where deleted_flag=0
                      and lower(btrim(style_name))=lower(btrim(?))
                      and lower(btrim(compatible_models))=lower(btrim(?))
                    """,command.styleName(),models);
                if(!duplicate.isEmpty()) throw new BusinessException(ErrorCodeConstants.CODE_CONFLICT,
                    "相同款式与兼容型号已有协作档案，请改为关联已有档案",Map.of("matches",duplicate));
                BigDecimal price=decimal(source.get("priceAmount"));
                String currency=text(source,"priceCurrency").toUpperCase(Locale.ROOT);
                String notes=notes(command.notes(),source,price,currency);
                if(price==null||blank(currency)) {price=null;currency=null;}
                Map<String,Object> item=collaboration.createItem(new CreateItem(
                    command.productLineId(),command.styleName(),text(source,"brand"),models,
                    blank(command.phoneModelCode())?null:command.phoneModelCode().trim(),price,currency,
                    text(source,"source_name"),text(source,"source_url"),notes),request);
                itemId=((Number)item.get("itemId")).longValue();
            }
            String snapshot;
            try {snapshot=json.writeValueAsString(source);} catch(JsonProcessingException ex) {throw new IllegalStateException(ex);}
            jdbc.update("""
                insert into plm_market_watch_link(source_kind,source_id,collaboration_item_id,source_snapshot,
                  promoted_by_id,promoted_by_name) values(?,?,?,cast(? as jsonb),?,?)
                on conflict(source_kind,source_id) do nothing
                """,command.sourceKind(),command.sourceId(),itemId,snapshot,actor.userId(),actor.displayName());
            Map<String,Object> saved=link(command.sourceKind(),command.sourceId()).orElseThrow();
            return promotionResult(saved,false);
        }));
    }

    private Map<String,Object> promotionResult(Map<String,Object> link,boolean idempotent) {
        return Map.of("itemId",link.get("itemId"),"alreadyPromoted",idempotent,"link",link);
    }

    private java.util.Optional<Map<String,Object>> link(String kind,long id) {
        List<Map<String,Object>> rows=jdbc.queryForList("""
            select source_kind as "sourceKind",source_id as "sourceId",collaboration_item_id as "itemId",
                   promoted_by_id as "promotedById",promoted_by_name as "promotedByName",promoted_at as "promotedAt"
              from plm_market_watch_link where source_kind=? and source_id=?
            """,kind,id);
        return rows.stream().findFirst();
    }

    private CurrentUser readGate() {
        if(!client.enabled()) throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND,"手机新品监控功能未启用");
        return actor();
    }

    private CurrentUser writeGate() {
        CurrentUser actor=readGate();
        if(!canWrite(actor)) throw new BusinessException(ErrorCodeConstants.FORBIDDEN,"只有市场负责人或管理员可以维护监控数据");
        return actor;
    }

    private CurrentUser actor() {
        CurrentUser session=CurrentUserContext.get().orElseThrow(()->new BusinessException(ErrorCodeConstants.UNAUTHORIZED,"请先登录"));
        List<Map<String,Object>> users=jdbc.queryForList(
            "select username,display_name,all_permissions from sys_user where user_id=? and deleted_flag=0 and status='active'",
            session.userId());
        if(users.isEmpty()) throw new BusinessException(ErrorCodeConstants.UNAUTHORIZED,"账号已失效");
        Map<String,Object> user=users.get(0);
        return new CurrentUser(session.userId(),Objects.toString(user.get("username"),session.username()),
            Objects.toString(user.get("display_name"),session.displayName()),Boolean.TRUE.equals(user.get("all_permissions")));
    }

    private boolean canWrite(CurrentUser actor) {
        if(actor.allPermissions()) return true;
        Long count=jdbc.queryForObject("select count(*) from plm_collaboration_assignment where field_group='market' and user_id=?",Long.class,actor.userId());
        return count!=null&&count>0;
    }

    private static String notes(String userNotes,Map<String,Object> source,BigDecimal amount,String currency) {
        String notes=blank(userNotes)?"":userNotes.trim();
        String raw=text(source,"price");
        if((amount==null||blank(currency))&&!blank(raw)) notes=(notes.isBlank()?"":notes+"\n")+"来源原始价格（币种/数值待确认）："+raw;
        return notes.isBlank()?null:notes;
    }

    private static BigDecimal decimal(Object value) {
        if(value==null||String.valueOf(value).isBlank()) return null;
        try{return new BigDecimal(String.valueOf(value));}catch(NumberFormatException ignored){return null;}
    }

    private static String text(Map<String,Object> source,String key) {return Objects.toString(source.get(key),"").trim();}
    private static boolean blank(String value) {return value==null||value.isBlank();}
    private static BusinessException invalid(String message) {return new BusinessException(ErrorCodeConstants.VALIDATION_ERROR,message);}
}
