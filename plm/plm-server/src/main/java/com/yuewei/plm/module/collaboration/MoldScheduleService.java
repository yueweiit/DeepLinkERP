package com.yuewei.plm.module.collaboration;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.vo.PageVO;
import com.yuewei.plm.module.pilot.PilotAccessService;
import jakarta.servlet.http.HttpServletRequest;
import java.time.*;
import java.util.*;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.transaction.support.TransactionTemplate;
import static com.yuewei.plm.module.collaboration.CollaborationFields.*;
import static com.yuewei.plm.module.collaboration.CollaborationTypes.*;

/** Thin facade over the shared collaboration ledger, mutation, audit and import engine. */
@Service @RequiredArgsConstructor
public class MoldScheduleService {
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    private final CollaborationService collaboration;
    private final CollaborationRepository repository;
    private final PilotAccessService access;
    private final org.springframework.transaction.PlatformTransactionManager transactionManager;
    private void read() {access.requireDomesticView();access.requirePermission("schedule:read");}
    public PageVO<Map<String,Object>> page(MoldScheduleTypes.Query query) {
        read();Query q=base(query);
        PageVO<Map<String,Object>> page=repository.page(q,collaboration.groups(collaboration.actor()),access.visibleSqlClause("mold","s.mold_set_id"));
        enrichPlans(page.getContent());return page;
    }
    private static Query base(MoldScheduleTypes.Query query) {
        Query q=new Query();q.setView("delivery");q.setMoldLedger(true);q.setSchedule(true);q.setPage(query.getPage());q.setSize(query.getSize());q.setKeyword(query.getKeyword());q.setProductLineId(query.getProductLineId());q.setMoldSetId(query.getMoldSetId());q.setStatus(query.getStatus());q.setMineOnly(query.isMineOnly());q.setOverdueOnly(query.isOverdueOnly());return q;
    }
    public Map<String,Object> detail(long id) {read();access.requireMold(id);Map<String,Object> row=repository.row("mold_set",id);enrichPlans(List.of(row));return row;}
    public Map<String,Object> options() {
        read();Map<String,Object> result=new LinkedHashMap<>(collaboration.options());
        result.put("scheduleFields",MoldScheduleTypes.FIELDS);result.put("styleDays",MoldScheduleTypes.STYLE_DAYS);
        result.put("transportDays",7);result.put("acceptanceDays",1);result.put("productionDays",3);
        result.put("remindersExternalEnabled",false);return result;
    }
    public List<RowResult> save(BatchSave dto,HttpServletRequest request) {
        access.requireDomesticView();access.requirePermission("schedule:write");
        for(RowPatch row:dto.rows()) {if(!row.entityType().equals("mold_set")) throw invalid("排程只保存模具套字段");access.requireMold(row.id());}
        List<RowResult> results=collaboration.save(dto,request);
        List<Map<String,Object>> rows=results.stream().map(RowResult::row).filter(Objects::nonNull).toList();enrichPlans(rows);
        return results;
    }
    /** The only mobile action field allowlist, reused by the mobile task facade. */
    private static final Map<String,Set<String>> MOBILE_FIELDS=Map.of(
        "processing",Set.of("pcStatus","tpuStatus"),
        "testing",Set.of("pcStatus","tpuStatus","actualSupplierTrialDate"),
        "ship",Set.of("actualShipDate","pcCurrentLocation","tpuCurrentLocation"),
        "arrival",Set.of("pcSignedDate","tpuSignedDate","pcFactoryArrivalDate","tpuFactoryArrivalDate"),
        "acceptance",Set.of("pcFactoryArrivalDate","tpuFactoryArrivalDate","pcAcceptanceStatus","tpuAcceptanceStatus","pcAcceptanceDate","tpuAcceptanceDate","pcAcceptanceIssues","tpuAcceptanceIssues"));
    public RowResult saveScopedTask(String action,RowPatch patch,HttpServletRequest request) {
        if(!MOBILE_FIELDS.containsKey(action)) throw invalid("手机任务操作无效");
        access.requirePermission("task:"+action);access.requireMold(patch.id());
        if(!patch.entityType().equals("mold_set")||patch.changes().stream().anyMatch(c->!MOBILE_FIELDS.get(action).contains(c.field()))) throw new BusinessException(40103,"手机任务包含未授权字段");
        return collaboration.save(new BatchSave(List.of(patch)),request).get(0);
    }
    public Map<String,Object> confirmPlan(long id,MoldScheduleTypes.ConfirmPlan dto) {
        access.requireDomesticView();access.requirePermission("schedule:write");access.requireMold(id);
        var actor=collaboration.actor();collaboration.requireGroup(actor,"engineering");
        return new TransactionTemplate(transactionManager).execute(tx->{
            jdbc.queryForList("select mold_set_id from plm_collaboration_mold_set where mold_set_id=? and deleted_flag=0 for update",id);
            Map<String,Object> row=repository.row("mold_set",id),snapshot=new LinkedHashMap<>();
            for(String key:MoldScheduleTypes.PLAN_KEYS) {
                if(!dto.before().containsKey(key)||!same(normalise(field("mold_set",key),dto.before().get(key)),row.get(key))) throw invalid("计划已变化，请刷新核对当前计划再留存基准");
                snapshot.put(key,row.get(key));
            }
            snapshot.put("styleName",row.get("styleName"));snapshot.put("compatibleModels",row.get("compatibleModels"));snapshot.put("defaultManufacturingDays",MoldScheduleTypes.defaultDays(Objects.toString(row.get("styleName"),"")));snapshot.put("transportDays",7);snapshot.put("acceptanceDays",1);snapshot.put("productionDays",3);
            if(row.get("plannedMoldDeliveryDate")==null||row.get("plannedFactoryArrivalDate")==null||row.get("plannedAcceptanceDate")==null||row.get("plannedProductionDate")==null) throw invalid("请先由各负责人确认完成、到厂、验收和量产四个计划日期，再留存基准版本");
            int version=Objects.requireNonNull(jdbc.queryForObject("select coalesce(max(version_no),0)+1 from plm_mold_schedule_plan where mold_set_id=?",Integer.class,id));
            jdbc.update("insert into plm_mold_schedule_plan(mold_set_id,version_no,plan_snapshot,reason,actor_id,actor_name) values(?,?,?::jsonb,?,?,?)",id,version,encode(snapshot),dto.reason(),actor.userId(),actor.username());
            jdbc.update("insert into plm_collaboration_history(item_id,entity_type,entity_id,field_name,before_value,after_value,reason,actor_id,actor_name) values(?,'mold_set',?,'planBaseline',null,?::jsonb,?,?,?)",row.get("itemId"),id,encode(Map.of("version",version,"snapshot",snapshot)),dto.reason(),actor.userId(),actor.username());
            enrichPlans(List.of(row));return row;
        });
    }
    public PageVO<Map<String,Object>> history(long id,int page,int size) {read();access.requireMold(id);return repository.moldHistory(id,page,size);}
    private void enrichPlans(List<Map<String,Object>> rows) {
        if(rows.isEmpty()) return;
        String placeholders=String.join(",",Collections.nCopies(rows.size(),"?"));Object[] ids=rows.stream().map(r->r.get("moldSetId")).toArray();
        var plans=jdbc.queryForList("select distinct on(mold_set_id) mold_set_id,version_no,plan_snapshot::text snapshot,reason,actor_name,confirmed_at from plm_mold_schedule_plan where mold_set_id in ("+placeholders+") order by mold_set_id,version_no desc",ids);
        Map<Long,Map<String,Object>> byId=new HashMap<>();plans.forEach(p->byId.put(((Number)p.get("mold_set_id")).longValue(),p));
        for(Map<String,Object> row:rows) {
            MoldScheduleTypes.enrich(row);var p=byId.get(((Number)row.get("moldSetId")).longValue());
            row.put("planVersion",p==null?0:p.get("version_no"));row.put("baseline",p==null?null:decode(p.get("snapshot")));
            row.put("baselineConfirmedAt",p==null?null:Objects.toString(p.get("confirmed_at"),null));row.put("baselineActor",p==null?null:p.get("actor_name"));
            row.put("baselineNeedsReview",p!=null&&java.util.stream.Stream.concat(MoldScheduleTypes.PLAN_KEYS.stream(),java.util.stream.Stream.of("styleName","compatibleModels")).anyMatch(k->!same(((Map<?,?>)row.get("baseline")).get(k),row.get(k))));
            row.put("tasks",tasksFor(row,LocalDate.now(ZoneId.of("Asia/Shanghai"))));
        }
    }
    static String missingSql(Set<String> groups) {
        List<String> clauses=new ArrayList<>();
        if(groups.contains("engineering")) clauses.add("s.opened_date is null or s.planned_mold_delivery_date is null or s.owner_user_id is null");
        if(groups.contains("logistics")) clauses.add("s.planned_factory_arrival_date is null or s.logistics_owner_user_id is null or (pc.status='ready' and tpu.status='ready' and s.actual_ship_date is null)");
        if(groups.contains("mexico")) clauses.add("s.planned_acceptance_date is null or s.planned_production_date is null or (s.actual_ship_date is not null and (pc.acceptance_status<>'passed' or tpu.acceptance_status<>'passed'))");
        return clauses.isEmpty()?"false":String.join(" or ",clauses.stream().map(c->"("+c+")").toList());
    }
    static String overdueSql() {
        return String.join(" or ",TASK_RULES.stream().map(rule -> "("+column(rule.due)+" < (now() at time zone 'Asia/Shanghai')::date and not coalesce(("+completeSql(rule)+"),false))").toList());
    }
    public record Task(long moldSetId,String assetNumber,String styleName,String compatibleModels,String taskKey,String title,String group,Long ownerUserId,String dueDate,boolean overdue) {}
    private record TaskRule(String key,String title,String group,String due,String owner,Map<String,String> requiredValues,List<String> requiredDates) {}
    private static final List<TaskRule> TASK_RULES=List.of(
        new TaskRule("mold_complete","确认模具制作完成","engineering","plannedMoldDeliveryDate","ownerUserId",Map.of("pcStatus","ready","tpuStatus","ready"),List.of()),
        new TaskRule("ship","填写实际发模","logistics","plannedMoldDeliveryDate","logisticsOwnerUserId",Map.of(),List.of("actualShipDate")),
        new TaskRule("factory_arrival","确认 PC / TPU 实际到厂","mexico","plannedFactoryArrivalDate","mexicoOwnerUserId",Map.of(),List.of("pcFactoryArrivalDate","tpuFactoryArrivalDate")),
        new TaskRule("acceptance","完成 PC / TPU 验收","mexico","plannedAcceptanceDate","mexicoOwnerUserId",Map.of("pcAcceptanceStatus","passed","tpuAcceptanceStatus","passed"),List.of("pcFactoryArrivalDate","tpuFactoryArrivalDate","pcAcceptanceDate","tpuAcceptanceDate")),
        new TaskRule("production","填写试模量产","mexico","plannedProductionDate","productionOwnerUserId",Map.of(),List.of("actualProductionDate")));
    private static boolean complete(Map<String,Object> row,TaskRule rule) {return rule.requiredValues.entrySet().stream().allMatch(e->e.getValue().equals(row.get(e.getKey())))&&rule.requiredDates.stream().allMatch(k->row.get(k)!=null);}
    static List<Task> tasksFor(Map<String,Object> row,LocalDate today) {
        return TASK_RULES.stream().filter(rule->!complete(row,rule)).map(rule->{LocalDate due=MoldScheduleTypes.date(row.get(rule.due));Object owner=row.get(rule.owner);return new Task(((Number)row.get("moldSetId")).longValue(),Objects.toString(row.get("assetNumber")),Objects.toString(row.get("styleName")),Objects.toString(row.get("compatibleModels")),rule.key,rule.title,rule.group,owner==null?null:((Number)owner).longValue(),due==null?null:due.toString(),due!=null&&due.isBefore(today));}).toList();
    }
    private static String column(String key) {Field f=field("mold_set",key);return (partField(f)?key.startsWith("pc")?"pc.":"tpu.":"s.")+f.column();}
    private static String completeSql(TaskRule rule) {List<String> clauses=new ArrayList<>();rule.requiredValues.forEach((key,value)->clauses.add(column(key)+"='"+value+"'"));rule.requiredDates.forEach(key->clauses.add(column(key)+" is not null"));return String.join(" and ",clauses);}
    public PageVO<Task> tasks(MoldScheduleTypes.Query query) {
        read();var actor=collaboration.actor();Set<String> groups=collaboration.groups(actor);
        return taskPage(query,access.visibleSqlClause("mold","s.mold_set_id"),groups,actor.userId());
    }
    /** Canonical task query shared by login-scoped pages and the trusted scheduler. */
    private PageVO<Task> taskPage(MoldScheduleTypes.Query query,String scope,Set<String> groups,Long actorId) {
        String values=String.join(",",TASK_RULES.stream().map(r->"('"+r.key+"','"+r.title+"','"+r.group+"',"+column(r.due)+","+column(r.owner)+",("+completeSql(r)+"))").toList());
        String from=" from plm_collaboration_mold_set s join plm_collaboration_item i on i.item_id=s.item_id left join plm_collaboration_mold_part pc on pc.mold_set_id=s.mold_set_id and pc.part_type='PC' left join plm_collaboration_mold_part tpu on tpu.mold_set_id=s.mold_set_id and tpu.part_type='TPU' cross join lateral (values "+values+") t(task_key,title,task_group,due_date,owner_id,completed)";
        StringBuilder where=new StringBuilder(" where i.deleted_flag=0 and s.deleted_flag=0 and not coalesce(t.completed,false) and (").append(scope).append(")");List<Object> args=new ArrayList<>();
        if(query.getMoldSetId()!=null) {where.append(" and s.mold_set_id=?");args.add(query.getMoldSetId());}
        if(query.getProductLineId()!=null) {where.append(" and i.product_line_id=?");args.add(query.getProductLineId());}
        if(query.getKeyword()!=null&&!query.getKeyword().isBlank()) {where.append(" and concat_ws(' ',i.style_name,i.compatible_models,s.set_name,"+CollaborationRepository.assetSql()+") ilike ?");args.add("%"+query.getKeyword().trim().replace("\\","\\\\").replace("%","\\%").replace("_","\\_")+"%");}
        if(query.getStatus()!=null) {where.append(" and (case when s.market_ready_date is not null then 'market_ready' else "+CollaborationRepository.moldStatusSql()+" end)=?");args.add(query.getStatus());}
        if(query.isMineOnly()) {where.append(" and (t.owner_id=? or (t.owner_id is null and t.task_group in (").append(groups.isEmpty()?"''":String.join(",",groups.stream().map(g->"'"+g+"'").toList())).append(")))");args.add(actorId);}
        String late="t.due_date < (now() at time zone 'Asia/Shanghai')::date";if(query.isOverdueOnly()) where.append(" and ").append(late);
        Long count=jdbc.queryForObject("select count(*)"+from+where,Long.class,args.toArray());long total=count==null?0:count;args.add(query.getSize());args.add((long)(query.getPage()-1)*query.getSize());
        List<Task> rows=jdbc.query("select s.mold_set_id,"+CollaborationRepository.assetSql()+" asset_number,i.style_name,i.compatible_models,t.task_key,t.title,t.task_group,t.owner_id,t.due_date,coalesce("+late+",false) overdue"+from+where+" order by t.due_date nulls last,s.mold_set_id,t.task_key limit ? offset ?",(rs,n)->new Task(rs.getLong("mold_set_id"),rs.getString("asset_number"),rs.getString("style_name"),rs.getString("compatible_models"),rs.getString("task_key"),rs.getString("title"),rs.getString("task_group"),(Long)rs.getObject("owner_id"),rs.getDate("due_date")==null?null:rs.getDate("due_date").toLocalDate().toString(),rs.getBoolean("overdue")),args.toArray());
        return new PageVO<>(rows,query.getPage(),query.getSize(),total,(total+query.getSize()-1)/query.getSize());
    }
    /** Persist station reminders only; no external DingTalk delivery is claimed. */
    public Map<String,Object> enqueueReminders() {
        access.requireAdministrator();access.requirePermission("schedule:remind");
        return enqueueTasks(access.actor().username(),access.visibleSqlClause("mold","s.mold_set_id"));
    }
    /** Trusted internal entry point: system actor, not a fabricated interactive account. */
    public Map<String,Object> enqueueAutomaticReminders() {return enqueueTasks("system","true");}
    @Scheduled(cron="${app.pilot.schedule-reminder-cron:0 0 * * * *}",zone="Asia/Shanghai")
    public void generateScheduledReminders() {enqueueAutomaticReminders();}
    private Map<String,Object> enqueueTasks(String createdBy,String scope) {
        int created=0,unassigned=0;
        MoldScheduleTypes.Query q=new MoldScheduleTypes.Query();q.setSize(100);q.setOverdueOnly(true);
        PageVO<Task> page;
        do {page=taskPage(q,scope,Set.of(),null);for(Task task:page.getContent()) {
            if(task.ownerUserId()==null) {unassigned++;continue;}
            created+=jdbc.update("insert into plm_mold_schedule_reminder(mold_set_id,task_key,due_date,recipient_id,payload,created_by) select ?,?,?,?,?::jsonb,? where exists(select 1 from sys_user where user_id=? and deleted_flag=0 and status='active') on conflict(mold_set_id,task_key,due_date,recipient_id) do nothing",task.moldSetId(),task.taskKey(),java.sql.Date.valueOf(task.dueDate()),task.ownerUserId(),encode(task),createdBy,task.ownerUserId());
        }q.setPage(q.getPage()+1);}while(q.getPage()<=page.getTotalPages());
        return Map.of("created",created,"unassigned",unassigned,"externalSent",0,"externalEnabled",false);
    }
    private String encode(Object value) {try{return json.writeValueAsString(value);}catch(Exception e){throw new IllegalStateException(e);}}
    private Object decode(Object value) {try{return json.readValue(value.toString(),new TypeReference<Object>(){});}catch(Exception e){throw new IllegalStateException(e);}}
}
