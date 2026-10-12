package com.yuewei.plm.module.pilotdelivery;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.infrastructure.storage.StorageClient;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.operationlog.service.OperationLogCreateCommand;
import com.yuewei.plm.module.pilot.PilotAccessService;
import jakarta.servlet.http.HttpServletRequest;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.OffsetDateTime;
import java.util.*;
import java.util.zip.*;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** One coherent relationship-preserving package, not another Excel export implementation. */
@Service @RequiredArgsConstructor
public class PilotExportService {
    private final JdbcTemplate jdbc;private final ObjectMapper json;private final PilotTrialService trials;
    private final PilotAccessService access;private final StorageClient storage;private final OperationLogService logs;
    private static final long MAX_BYTES=512L*1024*1024;
    private static final int MAX_REFERENCE_LEVELS=8,MAX_REFERENCE_RECORDS=5000;
    @Transactional(readOnly=true,isolation=org.springframework.transaction.annotation.Isolation.REPEATABLE_READ)
    public byte[] export(long id,HttpServletRequest request) {
        access.requireFinanceExport();Map<String,Object> trial=trials.raw(id);List<Long> projects=trials.projectIds(trial);
        if(projects.isEmpty())throw new BusinessException(40001,"请选择真实试点范围，不能导出整库历史资料");
        projects.forEach(access::requireProduct);String marks=PilotTrialService.marks(projects);Object[] args=projects.toArray();
        String items="select distinct i.item_id from plm_collaboration_item i where exists(select 1 from plm_collaboration_item_project ip where ip.item_id=i.item_id and ip.project_id in ("+marks+"))";
        String molds="select mold_set_id from plm_collaboration_mold_set where item_id in ("+items+")";
        String boms="select product_bom_id from plm_product_bom where product_id in ("+marks+")";
        var datasets=new LinkedHashMap<String,Object>();datasets.put("trial",trial);
        Map<String,String> selects=new LinkedHashMap<>();
        selects.put("products","select * from plm_product where product_id in ("+marks+")");
        selects.put("requirement_forms","select * from plm_project_requirement_form where project_id in ("+marks+")");
        selects.put("collaboration_items","select * from plm_collaboration_item where item_id in ("+items+")");
        selects.put("project_links","select * from plm_collaboration_item_project where item_id in ("+items+") and project_id in ("+marks+")");
        selects.put("mold_sets","select * from plm_collaboration_mold_set where mold_set_id in ("+molds+")");
        selects.put("mold_parts","select * from plm_collaboration_mold_part where mold_set_id in ("+molds+")");
        selects.put("mold_codes","select c.* from plm_product_mold_code c where c.product_id in ("+marks+") or c.product_mold_code_id in (select product_mold_code_id from plm_collaboration_mold_part where mold_set_id in ("+molds+"))");
        selects.put("referenced_products","select product_id,parent_product_id,product_code,product_name,product_type,model,phone_model_code,status from plm_product where product_id in (select product_id from plm_product_mold_code where product_mold_code_id in (select product_mold_code_id from plm_collaboration_mold_part where mold_set_id in ("+molds+"))) and product_id not in ("+marks+")");
        selects.put("mold_code_sources","select * from plm_mold_code_source where mold_code in(select original_mold_code from plm_collaboration_mold_part where mold_set_id in ("+molds+"))");
        selects.put("shipping_records","select * from plm_project_mold_transfer_express where project_id in ("+marks+")");
        selects.put("schedule_plans","select * from plm_mold_schedule_plan where mold_set_id in ("+molds+")");
        selects.put("schedule_reminders","select * from plm_mold_schedule_reminder where mold_set_id in ("+molds+")");
        selects.put("collaboration_history","select * from plm_collaboration_history where item_id in ("+items+")");
        selects.put("budgets","select * from plm_development_budget b where (b.budget_kind='platform' and b.product_line_id in ("+marks+")) or b.item_id in ("+items+")");
        selects.put("expenses","select * from plm_project_cost_item e where e.product_id in ("+marks+") or e.item_id in ("+items+") or (e.item_id is null and e.mold_set_id is null and e.product_line_id in ("+marks+"))");
        selects.put("boms","select * from plm_product_bom where product_bom_id in ("+boms+")");
        selects.put("bom_routes","select * from plm_product_bom_route where product_bom_id in ("+boms+")");
        selects.put("bom_items","select * from plm_product_bom_item where product_bom_id in ("+boms+")");
        selects.put("bom_colors","select * from plm_product_bom_route_color where product_bom_id in ("+boms+")");
        selects.put("bom_formal_selection","select * from plm_product_bom_route_formal_selection where product_bom_id in ("+boms+")");
        selects.put("production_color_decisions","select * from plm_product_production_color_decision where product_id in ("+marks+")");
        selects.put("production_operation_selection","select * from plm_process_production_operation_selection where product_id in ("+marks+")");
        selects.put("variant_colors","select * from plm_product_variant_color where project_product_id in ("+marks+")");
        selects.put("bom_cost_snapshots","select * from plm_product_bom_cost_snapshot where product_bom_id in ("+boms+")");
        selects.put("bom_releases","select * from plm_pilot_bom_release where bom_id in ("+boms+")");
        selects.put("referenced_processes","select * from plm_process where product_id in ("+marks+") or process_id in(select process_id from plm_product_bom_route where product_bom_id in ("+boms+"))");
        selects.put("workflow_templates","select * from plm_workflow_template where workflow_template_id in(select workflow_template_id from plm_product where product_id in ("+marks+")) or (active_flag=1 and flow_type in(select product_type from plm_product where product_id in ("+marks+")))");
        selects.put("workflow_nodes","select * from plm_workflow_template_node where workflow_template_id in(select workflow_template_id from plm_product where product_id in ("+marks+")) or workflow_template_id in(select workflow_template_id from plm_workflow_template where active_flag=1 and flow_type in(select product_type from plm_product where product_id in ("+marks+")))");
        selects.put("workflow_runtime","select product_id,workflow_template_id,workflow_template_version_no,current_step_no,timeline_current_confirmed,timeline_confirmed_node_key,timeline_last_action,timeline_last_reason,timeline_last_operated_at,timeline_last_operator_user_id,timeline_last_operator_user_name,lock_status,lock_reason,lock_operator_user_id,lock_operator_user_name,lock_operated_at from plm_product where product_id in ("+marks+")");
        selects.put("referenced_inventory","select * from plm_inventory where inventory_id in(select inventory_id from plm_product_bom_item where product_bom_id in ("+boms+")) or inventory_id in(select inventory_id from plm_collaboration_mold_part where mold_set_id in ("+molds+"))");
        selects.put("collaboration_import_rows","select * from plm_collaboration_import_row where item_id in ("+items+")");
        selects.put("collaboration_import_batches","select * from plm_collaboration_import_batch where batch_id in(select batch_id from plm_collaboration_import_row where item_id in ("+items+"))");
        // Placeholder count is derived from the code-owned query; no user SQL/table names are accepted.
        for(var entry:selects.entrySet()) {
            int count=(int)entry.getValue().chars().filter(c->c=='?').count();Object[] bound=new Object[count];for(int n=0;n<count;n++)bound[n]=args[n%args.length];
            datasets.put(entry.getKey(),records(entry.getValue(),bound));
        }
        Set<Long> authorized=new HashSet<>(projects);
        bomReferences(datasets,authorized);
        processReferences(datasets,authorized);
        productReferences(datasets,projects,authorized);
        if(!references(rows(datasets,"workflow_templates"),"workflow_template_id").containsAll(references(rows(datasets,"products"),"workflow_template_id")))throw incomplete("流程模板引用缺失");
        var budgetIds=ids(datasets.get("budgets"),"budget_id");var expenseIds=ids(datasets.get("expenses"),"project_cost_item_id");
        datasets.put("finance_history",history(budgetIds,expenseIds));
        List<Map<String,Object>> imports=new ArrayList<>();for(var group:Map.of("budget",budgetIds,"expense",expenseIds).entrySet())if(!group.getValue().isEmpty())imports.addAll(records("select * from plm_development_finance_import where import_kind=? and entity_id in ("+PilotTrialService.marks(group.getValue())+")",join(group.getKey(),group.getValue())));datasets.put("finance_import_sources",imports);
        datasets.put("trial_history",records("select * from plm_pilot_trial_history where trial_id=?",id));
        datasets.put("operation_logs",new ArrayList<>(records("select * from plm_operation_log where business_type in ('PRODUCT','PROJECT') and business_id in ("+marks+")",projects.stream().map(Object::toString).toArray())));
        List<Map<String,Object>> attachments=records("select * from plm_attachment where owner_object_type='Product' and owner_object_id in ("+marks+") and deleted_flag=0 order by attachment_id",args);
        Set<Long> attachmentReferences=references(attachments,"family_id","derived_pdf_attachment_id");attachmentReferences.removeAll(references(attachments,"attachment_id"));
        if(!attachmentReferences.isEmpty())throw incomplete("附件版本族根或 PDF 衍生件引用缺失、已删除或不在本次授权范围，请核对："+attachmentReferences);
        attachments.forEach(a->access.requireFile(((Number)a.get("attachment_id")).longValue()));datasets.put("attachments",attachments);
        List<Long> attachmentIds=ids(attachments,"attachment_id");if(!attachmentIds.isEmpty())((List<Map<String,Object>>)datasets.get("operation_logs")).addAll(records("select * from plm_operation_log where business_type='ATTACHMENT' and business_id in ("+PilotTrialService.marks(attachmentIds)+")",attachmentIds.stream().map(Object::toString).toArray()));
        List<Long> bomIds=ids(datasets.get("boms"),"product_bom_id");if(!bomIds.isEmpty())((List<Map<String,Object>>)datasets.get("operation_logs")).addAll(records("select * from plm_operation_log where business_type in('PRODUCT_BOM','ProductBom') and business_id in ("+PilotTrialService.marks(bomIds)+")",bomIds.stream().map(Object::toString).toArray()));
        datasets.put("workflow_history",rows(datasets,"operation_logs").stream().filter(r->Objects.toString(r.get("action"),"").startsWith("TIMELINE_")).toList());
        accountReferences(datasets);
        List<Map<String,Object>> manifest=new ArrayList<>();long size=0;
        try(var bytes=new ByteArrayOutputStream();var zip=new ZipOutputStream(bytes,StandardCharsets.UTF_8)) {
            write(zip,"README.txt",("本包是试点业务可读交付包，不是 PostgreSQL 全库恢复备份。\ndata/*.json 保留原始 ID、版本、状态、来源及审计；files/attachmentId/ 包含授权原文件，manifest.json 逐项提供 SHA-256。\nproducts/project_links 仅表示已选试点成员；referenced_* 是只读来源，不能作为新增试点成员或自动导入依据。\naccounts 仅含公开账号标识、名称、部门及状态，不含密码、手机号、令牌或登录配置。历史 system 等非账号标签原样保留。\nworkflow_runtime/history/templates/nodes 共同说明流程状态和运行记录；外部 ERP 发送、墨西哥网络和人员验收状态必须单独核对，导出不表示已完成联调。\n数据库恢复应使用经验证的独立数据库备份；本包不包含建库 SQL、环境秘密或自动恢复工具。\n").getBytes(StandardCharsets.UTF_8),manifest);
            for(var entry:datasets.entrySet())write(zip,"data/"+entry.getKey()+".json",json.writeValueAsBytes(entry.getValue()),manifest);
            for(var a:attachments){long aid=((Number)a.get("attachment_id")).longValue();String key=Objects.toString(a.get("storage_key"),"");
                if(!storage.exists(key))throw new BusinessException(40001,"原始附件缺失，不能宣称完整导出：附件 "+aid);
                String name=safeName(Objects.toString(a.get("original_file_name"),"file"));String target="files/"+aid+"/"+name;
                MessageDigest digest=MessageDigest.getInstance("SHA-256");long written=0;zip.putNextEntry(new ZipEntry(target));
                try(InputStream input=storage.loadAsResource(key).getInputStream()){byte[] buffer=new byte[64*1024];int n;while((n=input.read(buffer))!=-1){size+=n;written+=n;if(size>MAX_BYTES)throw new BusinessException(40001,"导出包超过512MB，请联系管理员分批归档");digest.update(buffer,0,n);zip.write(buffer,0,n);}}zip.closeEntry();
                String checksum=HexFormat.of().formatHex(digest.digest());if(a.get("checksum")!=null&&!checksum.equalsIgnoreCase(a.get("checksum").toString()))throw new BusinessException(40001,"原始附件校验不符：附件 "+aid);
                manifest.add(Map.of("path",target,"attachmentId",aid,"bytes",written,"sha256",checksum));
            }
            var index=Map.of("format","deeplink-plm-pilot-v1","trialId",id,"exportedAt",OffsetDateTime.now().toString(),"actorId",access.actorId(),"files",manifest,"dataOwnership","甲方","restoreOrder",List.copyOf(datasets.keySet()),"scope",Map.of("selectedProjectIds",projects,"referencedDatasetsAreReadOnly",true,"databaseRestoreBackup",false));
            zip.putNextEntry(new ZipEntry("manifest.json"));zip.write(json.writeValueAsBytes(index));zip.closeEntry();zip.finish();
            logs.logSuccess(OperationLogCreateCommand.builder().action("PILOT_EXPORT").businessType("PILOT_TRIAL").businessId(Long.toString(id)).detailJson("{\"files\":"+manifest.size()+"}").request(request).build());return bytes.toByteArray();
        }catch(BusinessException e){throw e;}catch(Exception e){throw new BusinessException(40001,"完整导出失败，原始数据未改动："+e.getClass().getSimpleName());}
    }
    /** Breadth-first lineage: a bounded number of batch queries, never one query per BOM/route. */
    private void bomReferences(Map<String,Object> data,Set<Long> authorized) {
        Set<Long> owned=new LinkedHashSet<>(ids(data.get("boms"),"product_bom_id"));
        Map<Long,Map<String,Object>> boms=index(rows(data,"boms"),"product_bom_id"),routes=index(rows(data,"bom_routes"),"product_bom_route_id");
        for(int level=0;level<MAX_REFERENCE_LEVELS;level++) {
            Set<Long> wantedRoutes=references(routes.values(),"source_product_bom_route_id");wantedRoutes.removeAll(routes.keySet());
            List<Map<String,Object>> sourceRoutes=batch("plm_product_bom_route","product_bom_route_id",wantedRoutes);
            if(sourceRoutes.size()!=wantedRoutes.size())throw incomplete("BOM 来源路线缺失");
            authorizeProducts(references(sourceRoutes,"product_id"),authorized);routes.putAll(index(sourceRoutes,"product_bom_route_id"));
            Set<Long> wantedBoms=references(boms.values(),"source_product_bom_id");wantedBoms.addAll(references(routes.values(),"product_bom_id"));wantedBoms.removeAll(boms.keySet());
            if(wantedBoms.isEmpty()&&wantedRoutes.isEmpty())break;
            var sourceBoms=batch("plm_product_bom","product_bom_id",wantedBoms);
            if(sourceBoms.size()!=wantedBoms.size())throw incomplete("BOM 来源版本缺失");
            authorizeProducts(references(sourceBoms,"product_id"),authorized);boms.putAll(index(sourceBoms,"product_bom_id"));
            if(!wantedBoms.isEmpty())routes.putAll(index(records("select * from plm_product_bom_route where product_bom_id in ("+PilotTrialService.marks(wantedBoms.stream().toList())+") limit "+(MAX_REFERENCE_RECORDS+1),wantedBoms.toArray()),"product_bom_route_id"));
            bounded(boms.size()+routes.size());
        }
        Set<Long> remaining=references(boms.values(),"source_product_bom_id");remaining.removeAll(boms.keySet());Set<Long> routeRemaining=references(routes.values(),"source_product_bom_route_id");routeRemaining.removeAll(routes.keySet());
        if(!remaining.isEmpty()||!routeRemaining.isEmpty())throw incomplete("BOM 来源超过八层或有缺失引用");
        var sourceBoms=boms.values().stream().filter(b->!owned.contains(number(b,"product_bom_id"))).toList();var sourceIds=references(sourceBoms,"product_bom_id");
        data.put("referenced_boms",sourceBoms);data.put("referenced_bom_routes",routes.values().stream().filter(r->sourceIds.contains(number(r,"product_bom_id"))).toList());
        for(var entry:Map.of("referenced_bom_items","plm_product_bom_item","referenced_bom_colors","plm_product_bom_route_color","referenced_bom_cost_snapshots","plm_product_bom_cost_snapshot").entrySet()){
            var values=sourceIds.isEmpty()?List.<Map<String,Object>>of():records("select * from "+entry.getValue()+" where product_bom_id in ("+PilotTrialService.marks(sourceIds.stream().toList())+") limit "+(MAX_REFERENCE_RECORDS+1),sourceIds.toArray());bounded(values.size());data.put(entry.getKey(),values);
        }
        Set<Long> inventory=references(rows(data,"referenced_bom_items"),"inventory_id");inventory.addAll(references(rows(data,"bom_items"),"inventory_id"));inventory.addAll(references(rows(data,"mold_parts"),"inventory_id"));inventory.removeAll(new HashSet<>(ids(data.get("referenced_inventory"),"inventory_id")));var extraInventory=batch("plm_inventory","inventory_id",inventory);if(extraInventory.size()!=inventory.size())throw incomplete("物料来源缺失");var allInventory=new ArrayList<>(rows(data,"referenced_inventory"));allInventory.addAll(extraInventory);data.put("referenced_inventory",allInventory);
    }
    private void processReferences(Map<String,Object> data,Set<Long> authorized) {
        Map<Long,Map<String,Object>> processes=index(rows(data,"referenced_processes"),"process_id");
        Set<Long> seed=references(rows(data,"bom_routes"),"process_id");seed.addAll(references(rows(data,"referenced_bom_routes"),"process_id"));seed.addAll(references(rows(data,"production_operation_selection"),"operation_process_id","process_id"));seed.removeAll(processes.keySet());
        var extra=batch("plm_process","process_id",seed);if(extra.size()!=seed.size())throw incomplete("工艺来源记录缺失");processes.putAll(index(extra,"process_id"));
        Set<Long> frontier=new LinkedHashSet<>(processes.keySet());
        for(int level=0;level<MAX_REFERENCE_LEVELS;level++) {
            Set<Long> parents=references(processes.values(),"parent_process_id","operation_master_process_id");parents.removeAll(processes.keySet());
            if(frontier.isEmpty()&&parents.isEmpty())break;
            var args=new ArrayList<Object>();StringBuilder where=new StringBuilder();
            if(!frontier.isEmpty()){where.append("parent_process_id in (").append(PilotTrialService.marks(frontier.stream().toList())).append(")");args.addAll(frontier);}
            if(!parents.isEmpty()){if(!where.isEmpty())where.append(" or ");where.append("process_id in (").append(PilotTrialService.marks(parents.stream().toList())).append(")");args.addAll(parents);}
            var loaded=records("select * from plm_process where "+where+" limit "+(MAX_REFERENCE_RECORDS+1),args.toArray());
            Set<Long> next=new LinkedHashSet<>();for(var row:loaded){long pid=number(row,"process_id");if(!processes.containsKey(pid))next.add(pid);processes.put(pid,row);}
            if(!processes.keySet().containsAll(parents))throw incomplete("工序母版或父路线缺失");frontier=next;bounded(processes.size());
        }
        if(!frontier.isEmpty())throw incomplete("工艺来源超过八层");
        authorizeProducts(references(processes.values(),"product_id"),authorized);data.put("referenced_processes",new ArrayList<>(processes.values()));
    }
    private void productReferences(Map<String,Object> data,List<Long> selected,Set<Long> authorized) {
        Map<Long,Map<String,Object>> products=index(rows(data,"referenced_products"),"product_id");Set<Long> known=new LinkedHashSet<>(selected);known.addAll(products.keySet());
        authorizeProducts(products.keySet(),authorized);
        Set<Long> needed=references(rows(data,"products"),"parent_product_id");needed.addAll(references(products.values(),"parent_product_id"));needed.addAll(references(rows(data,"referenced_boms"),"product_id","source_product_id"));needed.addAll(references(rows(data,"boms"),"source_product_id"));needed.addAll(references(rows(data,"referenced_processes"),"product_id"));needed.addAll(references(rows(data,"production_color_decisions"),"created_sku_product_id"));
        for(int level=0;level<MAX_REFERENCE_LEVELS;level++) {needed.removeAll(known);if(needed.isEmpty())break;
            var loaded=records("select product_id,parent_product_id,product_code,product_name,product_type,model,phone_model_code,status from plm_product where product_id in ("+PilotTrialService.marks(needed.stream().toList())+") limit "+(MAX_REFERENCE_RECORDS+1),needed.toArray());
            if(loaded.size()!=needed.size())throw incomplete("来源产品缺失");authorizeProducts(references(loaded,"product_id"),authorized);products.putAll(index(loaded,"product_id"));known.addAll(products.keySet());needed=references(loaded,"parent_product_id");bounded(known.size());
        }
        needed.removeAll(known);if(!needed.isEmpty())throw incomplete("来源产品超过八层");data.put("referenced_products",new ArrayList<>(products.values()));
    }
    private static final Set<String> ACCOUNT_IDS=Set.of("user_id","actor_id","owner_user_id","recipient_id","operator_user_id","timeline_last_operator_user_id","lock_operator_user_id","logistics_owner_user_id","mexico_owner_user_id","production_owner_user_id","released_by_user_id","created_by","updated_by","actorId","ownerUserId","logisticsOwnerUserId","mexicoOwnerUserId","productionOwnerUserId");
    private static final Set<String> ACCOUNT_NAMES=Set.of("created_by","updated_by","committed_by","released_by","frozen_by","confirmed_by","linked_by","actor_name","actorName");
    private void accountReferences(Map<String,Object> data) {
        Set<Long> ids=new LinkedHashSet<>();Set<String> names=new LinkedHashSet<>();if(access.actorId()>0)ids.add(access.actorId());collectAccounts(data,ids,names);bounded(ids.size()+names.size());
        List<Object> args=new ArrayList<>();List<String> conditions=new ArrayList<>();if(!ids.isEmpty()){conditions.add("user_id in ("+PilotTrialService.marks(ids.stream().toList())+")");args.addAll(ids);}if(!names.isEmpty()){conditions.add("username in ("+PilotTrialService.marks(names.stream().toList())+")");args.addAll(names);}
        var accounts=conditions.isEmpty()?List.<Map<String,Object>>of():records("select user_id,username,display_name,department_name,status,deleted_flag from sys_user where "+String.join(" or ",conditions)+" order by user_id",args.toArray());
        Set<Long> found=references(accounts,"user_id");if(!found.containsAll(ids))throw incomplete("真实账号引用缺失");Set<String> unresolved=new LinkedHashSet<>(names);accounts.forEach(a->unresolved.remove(Objects.toString(a.get("username"),"")));data.put("accounts",accounts);data.put("account_reference_notes",Map.of("unresolvedHistoricalLabels",unresolved,"message","历史 system/导入标签不是新造账号；原审计文本保留"));
    }
    private void authorizeProducts(Set<Long> references,Set<Long> authorized){
        Set<Long> needed=new LinkedHashSet<>(references);needed.removeAll(authorized);if(needed.isEmpty())return;bounded(needed.size());
        var allowed=records("select p.product_id from plm_product p where p.product_id in ("+PilotTrialService.marks(needed.stream().toList())+") and ("+access.visibleSqlClause("product","p.product_id")+")",needed.toArray());
        if(!references(allowed,"product_id").containsAll(needed))throw new BusinessException(40103,"来源引用包含未授权产品，不能完整导出；请由管理员确认授权");authorized.addAll(needed);
    }
    private void collectAccounts(Object value,Set<Long> ids,Set<String> names){
        if(value instanceof com.fasterxml.jackson.databind.JsonNode node){collectAccounts(json.convertValue(node,Object.class),ids,names);return;}
        if(value instanceof Map<?,?> map){for(var entry:map.entrySet()){String key=entry.getKey().toString();Object v=entry.getValue();if(ACCOUNT_IDS.contains(key)&&v instanceof Number n&&n.longValue()>0)ids.add(n.longValue());if(ACCOUNT_NAMES.contains(key)&&v instanceof String name&&!name.isBlank())names.add(name);collectAccounts(v,ids,names);}}else if(value instanceof Iterable<?> values)for(var v:values)collectAccounts(v,ids,names);
    }
    private List<Map<String,Object>> batch(String table,String key,Set<Long> ids){if(ids.isEmpty())return List.of();bounded(ids.size());var rows=records("select * from "+table+" where "+key+" in ("+PilotTrialService.marks(ids.stream().toList())+") limit "+(MAX_REFERENCE_RECORDS+1),ids.toArray());bounded(rows.size());return rows;}
    @SuppressWarnings("unchecked") private static List<Map<String,Object>> rows(Map<String,Object> data,String key){return (List<Map<String,Object>>)data.getOrDefault(key,List.of());}
    private static Map<Long,Map<String,Object>> index(Collection<Map<String,Object>> rows,String key){Map<Long,Map<String,Object>> result=new LinkedHashMap<>();for(var row:rows)result.put(number(row,key),row);return result;}
    private static Set<Long> references(Collection<Map<String,Object>> rows,String...keys){Set<Long> ids=new LinkedHashSet<>();for(var row:rows)for(String key:keys)if(row.get(key) instanceof Number n&&n.longValue()>0)ids.add(n.longValue());return ids;}
    private static long number(Map<String,Object> row,String key){return ((Number)row.get(key)).longValue();}
    private static void bounded(int size){if(size>MAX_REFERENCE_RECORDS)throw incomplete("来源引用超过5000条，请缩小试点范围");}
    private static BusinessException incomplete(String reason){return new BusinessException(40001,reason+"，不能宣称完整导出");}
    List<Map<String,Object>> records(String sql,Object...args){return jdbc.query(sql,(rs,n)->{Map<String,Object> row=new LinkedHashMap<>();var meta=rs.getMetaData();for(int c=1;c<=meta.getColumnCount();c++)row.put(meta.getColumnLabel(c),databaseValue(rs.getObject(c),meta.getColumnTypeName(c)));return row;},args);}
    private Object databaseValue(Object value,String type){try{if(value==null)return null;if(Set.of("json","jsonb").contains(type))return json.readTree(value.toString());if(value instanceof java.sql.Timestamp t)return t.toLocalDateTime().toString();if(value instanceof java.sql.Date d)return d.toLocalDate().toString();return value;}catch(java.io.IOException e){throw new BusinessException(40001,"导出数据JSON无效，不能生成不完整包");}}
    private List<Long> ids(Object rows,String key){return ((List<?>)rows).stream().map(r->((Number)((Map<?,?>)r).get(key)).longValue()).toList();}
    private Object[] join(Object first,List<Long> values){List<Object> args=new ArrayList<>();args.add(first);args.addAll(values);return args.toArray();}
    private List<Map<String,Object>> history(List<Long> budgets,List<Long> expenses){List<Map<String,Object>> result=new ArrayList<>();for(var kind:Map.of("budget",budgets,"expense",expenses).entrySet())if(!kind.getValue().isEmpty())result.addAll(records("select * from plm_development_finance_history where entity_type='"+kind.getKey()+"' and entity_id in ("+PilotTrialService.marks(kind.getValue())+")",kind.getValue().toArray()));return result;}
    static String safeName(String value){String clean=value.replaceAll("[\\\\/:\\p{Cntrl}]","_").replace("..","_");return clean.length()>180?clean.substring(clean.length()-180):clean;}
    private static void write(ZipOutputStream zip,String name,byte[] bytes,List<Map<String,Object>> manifest)throws Exception {zip.putNextEntry(new ZipEntry(name));zip.write(bytes);zip.closeEntry();manifest.add(Map.of("path",name,"bytes",bytes.length,"sha256",HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes))));}
}
