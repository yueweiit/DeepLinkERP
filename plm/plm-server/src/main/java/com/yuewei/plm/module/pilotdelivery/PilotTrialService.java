package com.yuewei.plm.module.pilotdelivery;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.module.pilot.PilotAccessService;
import java.time.LocalDate;
import java.util.*;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** Explicit trial membership; choosing seven platforms does not migrate their historical children. */
@Service @RequiredArgsConstructor
public class PilotTrialService {
    private final JdbcTemplate jdbc;private final ObjectMapper json;private final PilotAccessService access;private final PilotDeliveryQueue queue;
    public record Save(String name,List<Long> platformIds,Long newPlatformId,List<Long> projectIds,Map<String,Object> baseline,Integer beforeRevision,String reason) {}
    public record Start(LocalDate startedOn,boolean mexicoAccessVerified,boolean supplierVerified,boolean erpVerified) {}
    public record Review(LocalDate reviewOn,String reason,Map<String,Object> evidence,String outcome) {}
    private static final Set<String> BASELINE_FIELDS=Set.of("moldLeadDays","bomPushMinutes","fileLookupMinutes","communicationMinutes");
    public List<Map<String,Object>> list(){access.requireDomesticView();access.requirePermission("report:view");return jdbc.queryForList("select trial_id,name,status,started_on,review_on,revision from plm_pilot_trial t where exists(select 1 from plm_product p where (p.product_id=t.new_platform_id or t.platform_ids @> jsonb_build_array(p.product_id) or t.project_ids @> jsonb_build_array(p.product_id)) and "+access.visibleSqlClause("product","p.product_id")+") or "+(access.hasPermission("pilot:admin")?"true":"false")+" order by trial_id desc");}
    public Map<String,Object> options(){access.requireAdministrator();return Map.of("platforms",jdbc.queryForList("select product_id,product_name,product_code,status from plm_product where deleted_flag=0 and product_type='product_line' order by product_name"),"projects",jdbc.queryForList("select product_id,parent_product_id,product_name,model,status from plm_product where deleted_flag=0 and product_type='model_variant' order by updated_at desc limit 500"),"message","选定真实试点新业务；历史平台仅作母体关联，不自动纳入其全部存量项目");}
    public Map<String,Object> detail(long id){access.requireAdministrator();var row=raw(id);row.put("history",jdbc.queryForList("select history_id,reason,actor_id,changed_at,after_value::text after_value from plm_pilot_trial_history where trial_id=? order by history_id desc",id));return row;}
    Map<String,Object> raw(long id){var rows=jdbc.queryForList("select trial_id,name,platform_ids::text platform_ids,new_platform_id,project_ids::text project_ids,status,preparation_at,started_on,review_on,baseline::text baseline,revision from plm_pilot_trial where trial_id=?",id);if(rows.isEmpty())throw new BusinessException(40401,"试点不存在");var row=new LinkedHashMap<>(rows.get(0));for(String field:List.of("platform_ids","project_ids","baseline"))row.put(field,decode(row.get(field)));return row;}
    @Transactional public Map<String,Object> save(Long id,Save dto) {
        access.requireAdministrator();if(dto.name()==null||dto.name().isBlank())throw invalid("试点名称必填");
        List<Long> platforms=unique(dto.platformIds()),projects=unique(dto.projectIds());if(platforms.size()>7||projects.size()>500)throw invalid("最多七个老平台及500个明确选定项目");
        Map<String,Object> baseline=baseline(dto.baseline());
        if(dto.newPlatformId()!=null&&platforms.contains(dto.newPlatformId()))throw invalid("新品平台与七个老平台不能重复");
        for(long platform:platforms){access.requireProduct(platform);Boolean stable=jdbc.queryForObject("select product_type='product_line' and status in ('released','archived') from plm_product where product_id=?",Boolean.class,platform);if(!Boolean.TRUE.equals(stable))throw invalid("老平台必须是正式已发布或归档产品线");}
        List<Long> roots=new ArrayList<>(platforms);if(dto.newPlatformId()!=null){access.requireProduct(dto.newPlatformId());Boolean parent=jdbc.queryForObject("select product_type='product_line' from plm_product where product_id=?",Boolean.class,dto.newPlatformId());if(!Boolean.TRUE.equals(parent))throw invalid("新品必须选产品平台");roots.add(dto.newPlatformId());}
        for(long project:projects){access.requireProduct(project);Long parent=jdbc.queryForObject("select parent_product_id from plm_product where product_id=?",Long.class,project);if(!roots.contains(parent))throw invalid("试点项目必须属于选择的平台");}
        String before=null;int revision=1;
        if(id!=null){jdbc.queryForList("select trial_id from plm_pilot_trial where trial_id=? for update",id);var old=raw(id);if(!"preparing".equals(old.get("status")))throw invalid("试点开始后不能扩大范围；新增需求留在试点外清单");if(!Objects.equals(dto.beforeRevision(),((Number)old.get("revision")).intValue()))throw invalid("试点配置已被修改，请刷新确认");before=encode(old);revision=((Number)old.get("revision")).intValue()+1;
            jdbc.update("update plm_pilot_trial set name=?,platform_ids=?::jsonb,new_platform_id=?,project_ids=?::jsonb,baseline=?::jsonb,revision=?,updated_by=?,updated_at=now() where trial_id=?",dto.name().trim(),encode(platforms),dto.newPlatformId(),encode(projects),encode(baseline),revision,access.actorId(),id);
        }else{id=jdbc.queryForObject("insert into plm_pilot_trial(name,platform_ids,new_platform_id,project_ids,baseline,created_by,updated_by) values(?,?::jsonb,?,?::jsonb,?::jsonb,?,?) returning trial_id",Long.class,dto.name().trim(),encode(platforms),dto.newPlatformId(),encode(projects),encode(baseline),access.actorId(),access.actorId());}
        var row=raw(id);history(id,before,row,dto.reason());return row;
    }
    @Transactional public Map<String,Object> start(long id,Start dto){access.requireAdministrator();jdbc.queryForList("select trial_id from plm_pilot_trial where trial_id=? for update",id);var row=raw(id);
        if(!"preparing".equals(row.get("status")))throw invalid("只能启动尚在准备的试点");
        if(((List<?>)row.get("platform_ids")).size()!=7||row.get("new_platform_id")==null||((List<?>)row.get("project_ids")).isEmpty())throw invalid("请确认七个稳定平台、一款新品及真实衍生项目");
        List<Long> selected=((List<?>)row.get("project_ids")).stream().map(value->((Number)value).longValue()).toList();
        Set<Long> represented=new HashSet<>(jdbc.queryForList("select distinct parent_product_id from plm_product where deleted_flag=0 and product_type='model_variant' and product_id in ("+marks(selected)+")",Long.class,selected.toArray()));
        if(!represented.containsAll(((List<?>)row.get("platform_ids")).stream().map(value->((Number)value).longValue()).toList()))throw invalid("七个稳定平台均须选择真实衍生项目，不能只勾选平台名称启动试点");
        if(!baseline((Map<String,Object>)row.get("baseline")).keySet().containsAll(BASELINE_FIELDS))throw invalid("请先采集四项真实手工模式基准；未知留空不能作为零值基准");
        if(dto.startedOn()==null||!dto.mexicoAccessVerified()||!dto.supplierVerified()||!dto.erpVerified())throw invalid("请完成墨西哥真实访问、供应商操作及ERP闭环验证后再启动");
        if(!queue.enabled()||!queue.configured("erp_bom")||!queue.expenseConfigured()||!queue.configured("dingtalk_reminder"))throw invalid("外部对接尚未启用或不完整（BOM发送、ERP费用只读、钉钉），不能将本地测试标记为正式试点启动");
        Long mexico=jdbc.queryForObject("select count(*) from plm_pilot_account a join sys_user u on u.user_id=a.user_id where a.role_code='mexico' and u.deleted_flag=0 and u.status='active'",Long.class);
        if(mexico==null||mexico<2||mexico>3)throw invalid("请配置2至3名真实墨西哥关键用户");
        jdbc.update("update plm_pilot_trial set status='active',started_on=?,review_on=?,updated_by=?,revision=revision+1,updated_at=now() where trial_id=?",dto.startedOn(),dto.startedOn().plusDays(27),access.actorId(),id);
        var next=raw(id);history(id,encode(row),Map.of("trial",next,"administratorAttestation",dto),"管理员确认真实参与方访问和接口闭环后启动四周试点（非系统自动检测）");return next;
    }
    @Transactional public Map<String,Object> review(long id,Review dto){access.requireAdministrator();jdbc.queryForList("select trial_id from plm_pilot_trial where trial_id=? for update",id);var old=raw(id);if(!"active".equals(old.get("status")))throw invalid("仅运行中的试点可以评审或书面延期");
        if(dto.reason()==null||dto.reason().isBlank()||dto.reviewOn()==null)throw invalid("评审日期和书面依据必填");LocalDate start=java.sql.Date.valueOf(old.get("started_on").toString()).toLocalDate();
        if(dto.reviewOn().isBefore(start)||dto.reviewOn().isAfter(start.plusDays(41)))throw invalid("评审不得早于启动，书面延期最多两周");
        if(!Set.of("active","passed","failed").contains(Objects.toString(dto.outcome(),"")))throw invalid("评审结果无效");
        if("active".equals(dto.outcome())&&dto.evidence()!=null&&!dto.evidence().isEmpty())throw invalid("延期不填评估结果，请在真实业务评审时提交");
        if(!"active".equals(dto.outcome())&&(dto.evidence()==null||dto.evidence().isEmpty()))throw invalid("通过或不通过须提供真实业务评审证据");
        if(!"active".equals(dto.outcome()))validateEvidence(dto.evidence());
        jdbc.update("update plm_pilot_trial set status=?,review_on=?,extension_reason=?,updated_by=?,revision=revision+1,updated_at=now() where trial_id=?",dto.outcome(),dto.reviewOn(),dto.reason(),access.actorId(),id);var next=raw(id);history(id,encode(old),Map.of("trial",next,"evidence",dto.evidence()==null?Map.of():dto.evidence()),dto.reason());return next;
    }
    public Map<String,Object> metrics(long id){access.requireDomesticView();access.requirePermission("report:view");var trial=raw(id);List<Long> ids=projectIds(trial);Map<String,Object> summary=Map.of("trial_id",id,"name",trial.get("name"),"status",trial.get("status"));if(ids.isEmpty()){access.requireAdministrator();return Map.of("trial",summary,"projects",List.of(),"baseline",baseline((Map<String,Object>)trial.get("baseline")),"message","尚未选定真实业务；不生成演示指标");}
        String marks=marks(ids);var projects=jdbc.queryForList("select product_id,parent_product_id,product_code,product_name,model,status,created_at,updated_at from plm_product p where product_id in ("+marks+") and "+access.visibleSqlClause("product","p.product_id"),ids.toArray());
        var files=jdbc.queryForObject("select count(*) from plm_attachment a where owner_object_type='Product' and owner_object_id in ("+marks+") and deleted_flag=0 and "+access.visibleSqlClause("file","a.attachment_id"),Long.class,ids.toArray());
        if(projects.isEmpty())throw new BusinessException(40301,"没有该试点的授权项目");
        var reviews=jdbc.queryForList("select (after_value->'evidence')::text as evidence,reason,actor_id,changed_at from plm_pilot_trial_history where trial_id=? and jsonb_exists(after_value,'evidence') order by history_id desc limit 1",id);
        reviews.forEach(r->{if(r.get("evidence")!=null)r.put("evidence",decode(r.get("evidence")));});
        return Map.of("trial",summary,"projects",projects,"fileCount",files,"baseline",baseline((Map<String,Object>)trial.get("baseline")),"reviews",reviews,"message","计划/实际及费用从各自唯一业务服务查询；PLM不承诺缩短物理加工和运输时长");
    }
    List<Long> projectIds(Map<String,Object> trial){List<Long> ids=new ArrayList<>();for(Object id:(List<?>)trial.get("platform_ids"))ids.add(((Number)id).longValue());if(trial.get("new_platform_id")!=null)ids.add(((Number)trial.get("new_platform_id")).longValue());for(Object id:(List<?>)trial.get("project_ids"))ids.add(((Number)id).longValue());return ids.stream().distinct().toList();}
    private static List<Long> unique(List<Long> ids){if(ids==null)return List.of();if(ids.stream().anyMatch(v->v==null||v<1))throw invalid("对象ID无效");return ids.stream().distinct().toList();}
    private static Map<String,Object> baseline(Map<String,Object> values){Map<String,Object> result=new LinkedHashMap<>();if(values==null)return result;for(var entry:values.entrySet()){if(!BASELINE_FIELDS.contains(entry.getKey()))throw invalid("基准只接受已定义的工时或周期指标，不接受自由金额字段");if(entry.getValue()==null)continue;if(!(entry.getValue() instanceof Number n)||!Double.isFinite(n.doubleValue())||n.doubleValue()<0)throw invalid("基准须为非负数，未知留空");result.put(entry.getKey(),entry.getValue());}return result;}
    private static void validateEvidence(Map<String,Object> values){if(!(values.get("notes") instanceof String notes)||notes.isBlank())throw invalid("请说明真实业务记录、证据位置及未完成链路");for(var entry:values.entrySet()){if(entry.getKey().equals("notes"))continue;if(!BASELINE_FIELDS.contains(entry.getKey())&&!entry.getKey().equals("businessCount"))throw invalid("评估指标仅接受已定义的周期和工时，不接受自由金额字段");if(entry.getValue()!=null&&(!(entry.getValue() instanceof Number n)||!Double.isFinite(n.doubleValue())||n.doubleValue()<0))throw invalid("真实评估指标须为非负数，未知留空");}}
    static String marks(List<?> ids){return String.join(",",Collections.nCopies(ids.size(),"?"));}
    private void history(long id,String before,Object after,String reason){jdbc.update("insert into plm_pilot_trial_history(trial_id,before_value,after_value,reason,actor_id) values(?,?::jsonb,?::jsonb,?,?)",id,before,encode(after),reason,access.actorId());}
    String encode(Object value){try{return json.writeValueAsString(value);}catch(Exception e){throw invalid("试点数据无法序列化");}}
    Object decode(Object value){try{return json.readValue(value.toString(),new TypeReference<Object>(){});}catch(Exception e){throw invalid("试点数据无法解析");}}
    private static BusinessException invalid(String message){return new BusinessException(40001,message);}
}
