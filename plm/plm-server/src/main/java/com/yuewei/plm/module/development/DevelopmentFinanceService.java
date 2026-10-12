package com.yuewei.plm.module.development;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.common.vo.PageVO;
import com.yuewei.plm.module.operationlog.service.OperationLogCreateCommand;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.pilot.PilotAccessService;
import jakarta.servlet.http.HttpServletRequest;
import java.math.BigDecimal;
import java.sql.*;
import java.time.*;
import java.util.*;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import static com.yuewei.plm.module.development.DevelopmentTypes.*;
import static com.yuewei.plm.module.development.DevelopmentFinanceMath.*;

/** One expense ledger and one state machine shared by the new views and legacy project routes. */
@Service @RequiredArgsConstructor
public class DevelopmentFinanceService {
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    private final PilotAccessService access;
    private final PlatformTransactionManager transactionManager;
    private final OperationLogService operationLog;
    private static final Map<String,String> BUDGET_FIELDS=Map.ofEntries(
        Map.entry("budgetName","budget_name"),Map.entry("calculationMode","calculation_mode"),Map.entry("budgetAmount","budget_amount"),Map.entry("moldCost","mold_cost"),
        Map.entry("moldWeight","mold_weight"),Map.entry("transportRate","transport_rate"),Map.entry("fuelRate","fuel_rate"),
        Map.entry("customsCost","customs_cost"),Map.entry("salePrice","sale_price"),Map.entry("unitProductionCost","unit_production_cost"),Map.entry("notes","notes"));
    private static final Map<String,String> EXPENSE_FIELDS=Map.ofEntries(
        Map.entry("description","cost_name"),Map.entry("expenseCategory","cost_category"),Map.entry("declaredAmount","amount"),
        Map.entry("requestedAmount","requested_amount"),Map.entry("approvedAmount","approved_amount"),
        Map.entry("approvalInstanceId","approval_instance_id"),Map.entry("approvalStatus","approval_status"),
        Map.entry("supplierName","supplier_name"),Map.entry("occurredAt","occurred_at"),Map.entry("notes","remark"),Map.entry("state","status"),
        Map.entry("productLineId","product_line_id"),Map.entry("itemId","item_id"),Map.entry("moldSetId","mold_set_id"),Map.entry("budgetId","budget_id"));
    private static final String BUDGET_SELECT="select b.*,p.product_name as product_line_name,i.style_name,i.compatible_models,s.set_no,s.set_name,f.requested_total,f.approved_total,f.declared_total,f.erp_posted_net ";
    private static final String BUDGET_FROM=" from plm_development_budget b left join plm_product p on p.product_id=b.product_line_id left join plm_collaboration_item i on i.item_id=b.item_id left join plm_collaboration_mold_set s on s.mold_set_id=b.mold_set_id left join (select budget_id,currency_code,sum(requested_amount) as requested_total,sum(approved_amount) as approved_total,sum(amount) filter(where source_system='manual' and status='confirmed') as declared_total,sum(erp_posted_amount) filter(where source_system='erp') as erp_posted_net from plm_project_cost_item where deleted_flag=0 and status<>'void' and budget_id is not null group by budget_id,currency_code) f on f.budget_id=b.budget_id and f.currency_code=b.currency_code ";
    private static final String EXPENSE_SELECT="select e.*,e.project_cost_item_id as expense_id,e.cost_name as description,e.cost_category as expense_category,e.amount as declared_amount,e.status as state,e.remark as notes,p.product_name as product_line_name,i.style_name,i.compatible_models,b.budget_name ";
    private static final String EXPENSE_FROM=" from plm_project_cost_item e left join plm_product p on p.product_id=e.product_line_id left join plm_collaboration_item i on i.item_id=e.item_id left join plm_development_budget b on b.budget_id=e.budget_id ";
    private static String table(String entity){return entity.equals("budget")?"plm_development_budget":"plm_project_cost_item";}
    private static String idColumn(String entity){return entity.equals("budget")?"budget_id":"project_cost_item_id";}
    private static Map<String,String> fields(String entity){return entity.equals("budget")?BUDGET_FIELDS:EXPENSE_FIELDS;}
    private String visible(String entity) {
        String a=entity.equals("budget")?"b":"e";
        String item=access.visibleSqlClause("item",a+".item_id"),mold=access.visibleSqlClause("mold",a+".mold_set_id"),product=access.visibleSqlClause("product",a+".product_line_id");
        String known="("+a+".mold_set_id is not null and ("+mold+")) or ("+a+".mold_set_id is null and "+a+".item_id is not null and ("+item+")) or ("+a+".item_id is null and "+a+".product_line_id is not null and ("+product+"))";
        if(!entity.equals("budget")) known+=" or (e.product_line_id is null and e.item_id is null and e.product_id is not null and ("+access.visibleSqlClause("product","e.product_id")+"))";
        if(access.actor().allPermissions()) return "true";
        return "("+known+")";
    }
    private record Filter(String where,List<Object> args) {}
    private Filter filter(String entity,Query q) {
        String a=entity.equals("budget")?"b":"e";List<Object> args=new ArrayList<>();StringBuilder sql=new StringBuilder(" where "+a+".deleted_flag=0 and ("+visible(entity)+")");
        if(q.getKeyword()!=null&&!q.getKeyword().isBlank()) {sql.append(" and concat_ws(' ',").append(entity.equals("budget")?"b.budget_name":"e.cost_name,e.erp_voucher_id,e.erp_line_id").append(",p.product_name,i.style_name,i.compatible_models) ilike ?");args.add("%"+q.getKeyword().trim().replace("\\","\\\\").replace("%","\\%").replace("_","\\_")+"%");}
        if(q.getProductLineId()!=null){sql.append(" and ").append(a).append(".product_line_id=?");args.add(q.getProductLineId());}
        if(entity.equals("expense")&&q.getProductId()!=null){access.requireProduct(q.getProductId());sql.append(" and e.product_id=?");args.add(q.getProductId());}
        if(q.getItemId()!=null){sql.append(" and ").append(a).append(".item_id=?");args.add(q.getItemId());}
        if(q.getCurrency()!=null){sql.append(" and ").append(a).append(".currency_code=?");args.add(q.getCurrency());}
        if(entity.equals("budget")&&q.getKind()!=null){sql.append(" and b.budget_kind=?");args.add(q.getKind());}
        if(entity.equals("expense")&&q.getState()!=null){sql.append(" and e.status=?");args.add(q.getState());}
        if(q.getBudgetId()!=null){sql.append(entity.equals("budget")?" and b.budget_id=?":" and e.budget_id=?");args.add(q.getBudgetId());}
        return new Filter(sql.toString(),args);
    }
    public PageVO<Map<String,Object>> page(String entity,Query query) {
        access.requireFinanceRead();Filter f=filter(entity,query);String from=entity.equals("budget")?BUDGET_FROM:EXPENSE_FROM;
        Long total=jdbc.queryForObject("select count(*)"+from+f.where,Long.class,f.args.toArray());
        List<Object> args=new ArrayList<>(f.args);args.add(query.getSize());args.add((long)(query.getPage()-1)*query.getSize());
        String select=entity.equals("budget")?BUDGET_SELECT:EXPENSE_SELECT;String alias=entity.equals("budget")?"b":"e";
        List<Map<String,Object>> rows=jdbc.query(select+from+f.where+" order by "+alias+".updated_at desc,"+alias+"."+idColumn(entity)+" desc limit ? offset ?",this::map,args.toArray());
        return new PageVO<>(rows,query.getPage(),query.getSize(),total==null?0:total,total==null?0:(total+query.getSize()-1)/query.getSize());
    }
    public Map<String,Object> detail(String entity,long id) {
        access.requireFinanceRead();String a=entity.equals("budget")?"b":"e";
        var rows=jdbc.query((entity.equals("budget")?BUDGET_SELECT+BUDGET_FROM:EXPENSE_SELECT+EXPENSE_FROM)+" where "+a+"."+idColumn(entity)+"=? and "+a+".deleted_flag=0 and ("+visible(entity)+")",this::map,id);
        if(rows.isEmpty()) throw new BusinessException(40103,"记录不存在或未获授权");return rows.get(0);
    }
    public Map<String,Object> options() {
        access.requireFinanceRead();
        var lines=jdbc.query("select p.product_id,p.product_name,p.product_code from plm_product p where p.deleted_flag=0 and p.product_type='product_line' and ("+access.visibleSqlClause("product","p.product_id")+") order by p.product_name",this::map);
        var items=jdbc.query("select i.item_id,i.product_line_id,i.style_name,i.compatible_models from plm_collaboration_item i where i.deleted_flag=0 and ("+access.visibleSqlClause("item","i.item_id")+") order by i.style_name,i.compatible_models",this::map);
        var molds=jdbc.query("select s.mold_set_id,s.item_id,s.set_no,s.set_name from plm_collaboration_mold_set s where s.deleted_flag=0 and ("+access.visibleSqlClause("mold","s.mold_set_id")+") order by s.mold_set_id",this::map);
        var budgets=jdbc.query(BUDGET_SELECT+BUDGET_FROM+" where b.deleted_flag=0 and ("+visible("budget")+") order by b.budget_id",this::map);
        return Map.of("productLines",lines,"items",items,"molds",molds,"budgets",budgets,"writable",access.hasPermission("finance:write"),"confirmable",access.hasPermission("finance:confirm"),"exportable",access.hasPermission("finance:export"));
    }
    private void scope(Long product,Long item,Long mold) {
        if(product!=null) access.requireProduct(product);
        if(item!=null) {
            access.requireItem(item);var data=jdbc.queryForMap("select product_line_id from plm_collaboration_item where item_id=? and deleted_flag=0",item);
            if(product!=null&&!same(product,data.get("product_line_id"))) throw invalid("产品平台与协作档案不一致");
        }
        if(mold!=null) {
            access.requireMold(mold);Long owner=jdbc.queryForObject("select item_id from plm_collaboration_mold_set where mold_set_id=? and deleted_flag=0",Long.class,mold);
            if(item==null||!same(item,owner)) throw invalid("模具套不属于所选协作档案");
        }
    }
    private String currency(String value){String code=value==null?"CNY":value;if(!Set.of("CNY","MXN","USD","EUR").contains(code)) throw invalid("请选择原币，不能猜测或混币加总");return code;}
    public Map<String,Object> createBudget(CreateBudget dto,HttpServletRequest request) {
        access.requireFinanceWrite();scope(dto.productLineId(),dto.itemId(),dto.moldSetId());String code=currency(dto.currency());
        if(dto.kind().equals("platform")&&(dto.productLineId()==null||dto.itemId()!=null||dto.moldSetId()!=null||dto.parentBudgetId()!=null)) throw invalid("平台预算只绑定一个产品平台");
        if(dto.productLineId()!=null&&jdbc.queryForObject("select count(*) from plm_product where product_id=? and product_type='product_line' and deleted_flag=0",Long.class,dto.productLineId())==0)throw invalid("请选择真实产品平台，不按颜色项目重复预算");
        if(dto.kind().equals("mold")&&dto.itemId()==null) throw invalid("模具预算须绑定不分颜色的协作档案");
        if(dto.parentBudgetId()!=null) {var parent=detail("budget",dto.parentBudgetId());if(!parent.get("budgetKind").equals("platform")||!same(parent.get("productLineId"),dto.productLineId())||!code.equals(parent.get("currencyCode"))) throw invalid("父预算须为同平台同币种；父子预算不能相加");}
        return new TransactionTemplate(transactionManager).execute(tx->{var actor=access.actor();Long id;
            try {id=jdbc.queryForObject("insert into plm_development_budget(budget_kind,budget_name,product_line_id,item_id,mold_set_id,parent_budget_id,currency_code,transport_rate,fuel_rate,created_by,updated_by) values(?,?,?,?,?,?,?,?,?,?,?) returning budget_id",Long.class,dto.kind(),dto.name().trim(),dto.productLineId(),dto.itemId(),dto.moldSetId(),dto.parentBudgetId(),code,dto.kind().equals("mold")&&code.equals("CNY")?TRANSPORT_RATE:null,dto.kind().equals("mold")&&code.equals("CNY")?FUEL_RATE:null,actor.username(),actor.username());}
            catch(org.springframework.dao.DuplicateKeyException e){throw invalid("同一核算对象与币种已有预算，请修改原预算形成新版本，不按颜色重复创建");}
            if(dto.kind().equals("mold")) jdbc.update("update plm_development_budget set calculation_mode='mold_formula' where budget_id=?",id);
            var row=detail("budget",id);history("budget",id,1,"__created",null,row,"新增预算",actor);log("budget",id,"DEVELOPMENT_BUDGET_CREATE",request);return row;});
    }
    public Map<String,Object> createExpense(CreateExpense dto,HttpServletRequest request) {
        return createExpense(dto,dto.productId(),request);
    }
    public Map<String,Object> createExpense(CreateExpense dto,Long legacyProductId,HttpServletRequest request) {
        access.requireFinanceWrite();if(legacyProductId!=null) access.requireProduct(legacyProductId);
        scope(dto.productLineId(),dto.itemId(),dto.moldSetId());String code=currency(dto.currency());
        if(dto.productLineId()==null&&dto.itemId()==null&&legacyProductId==null) throw invalid("费用须明确关联平台或协作档案；不按金额猜测关系");
        validateBudget(dto.budgetId(),dto.productLineId(),dto.itemId(),dto.moldSetId(),code);
        return new TransactionTemplate(transactionManager).execute(tx->{var actor=access.actor();Long id=jdbc.queryForObject("insert into plm_project_cost_item(product_id,cost_name,cost_category,product_line_id,item_id,mold_set_id,budget_id,currency_code,created_by,updated_by) values(?,?,'mold',?,?,?,?,?,?,?) returning project_cost_item_id",Long.class,legacyProductId,text(dto.description(),128,true),dto.productLineId(),dto.itemId(),dto.moldSetId(),dto.budgetId(),code,actor.username(),actor.username());
            var row=detail("expense",id);history("expense",id,null,"__created",null,row,"新增费用草稿",actor);log("expense",id,"COST_ITEM_CREATE",request);return row;});
    }
    private void validateBudget(Long id,Long product,Long item,Long mold,String code) {
        if(id==null) return;var b=detail("budget",id);
        if(!code.equals(b.get("currencyCode"))) throw invalid("费用与预算币种不同，请按原币归集，不自动换算");
        if(b.get("itemId")!=null&&!same(b.get("itemId"),item)) throw invalid("费用不能归到其他档案预算");
        if(b.get("moldSetId")!=null&&!same(b.get("moldSetId"),mold)) throw invalid("费用不能归到其他模具套预算");
        if(b.get("productLineId")!=null&&!same(b.get("productLineId"),product)) throw invalid("费用与预算所属平台不一致");
    }
    public List<Result> save(String entity,Batch batch,HttpServletRequest request) {
        access.requireFinanceWrite();List<Result> results=new ArrayList<>();
        for(var patch:batch.rows()) try {results.add(new TransactionTemplate(transactionManager).execute(tx->saveRow(entity,patch,request)));}
        catch(BusinessException e){results.add(new Result(patch.id(),e.getCode()==40103?"forbidden":"invalid",e.getMessage(),List.of(),null));}
        catch(org.springframework.dao.DataIntegrityViolationException e){results.add(new Result(patch.id(),"invalid","关联或数据约束冲突，请核对记录",List.of(),null));}
        return results;
    }
    private Object normalise(String field,JsonNode value) {
        if(Set.of("budgetAmount","moldCost","customsCost","requestedAmount","approvedAmount").contains(field)) return amount(value,2,false);
        if(field.equals("declaredAmount")) return amount(value,6,false);
        if(Set.of("transportRate","fuelRate","salePrice","unitProductionCost").contains(field)) return amount(value,4,false);
        if(field.equals("moldWeight")) return amount(value,3,false);
        String text=value==null||value.isNull()?null:value.asText().trim();if(text!=null&&text.isEmpty()) text=null;
        if(field.endsWith("Id")&&!field.equals("approvalInstanceId")) {if(text==null)return null;try {long id=Long.parseLong(text);if(id<1)throw invalid("关联 ID 无效");return id;}catch(NumberFormatException e){throw invalid("关联 ID 无效");}}
        if(field.equals("occurredAt")){if(text==null)return null;try{return LocalDateTime.parse(text.length()==10?text+"T00:00:00":text);}catch(Exception e){throw invalid("发生日期格式不正确");}}
        if(field.equals("state")&&!Set.of("draft","confirmed","void").contains(Objects.toString(text,""))) throw invalid("费用状态无效");
        if(field.equals("calculationMode")&&!Set.of("manual","mold_formula").contains(Objects.toString(text,""))) throw invalid("预算测算方式无效");
        if(field.equals("expenseCategory")&&!Set.of("mold","other").contains(Objects.toString(text,""))) throw invalid("费用分类只支持模具或其他");
        if(field.equals("approvalStatus")&&!Set.of("unknown","requested","approved","rejected").contains(Objects.toString(text,""))) throw invalid("审批状态无效");
        return text(text,field.equals("description")?128:field.equals("budgetName")?255:field.equals("notes")?4000:255,Set.of("description","budgetName").contains(field));
    }
    private String text(String value,int max,boolean required){if(value==null||value.isBlank()){if(required)throw invalid("名称不能为空");return null;}if(value.length()>max)throw invalid("文字超出长度限制");return value.trim();}
    private Result saveRow(String entity,Patch patch,HttpServletRequest request) {
        jdbc.queryForList("select "+idColumn(entity)+" from "+table(entity)+" where "+idColumn(entity)+"=? for update",patch.id());
        var current=detail(entity,patch.id());Map<String,Object> next=new LinkedHashMap<>(current);Set<String> seen=new HashSet<>();List<Map<String,Object>> conflicts=new ArrayList<>();
        for(Change c:patch.changes()) {
            if(!fields(entity).containsKey(c.field())||!seen.add(c.field())) throw invalid("不能修改或重复提交字段："+c.field());
            Object before=normalise(c.field(),c.before()),after=normalise(c.field(),c.after());
            if(!same(current.get(c.field()),before)){var conflict=new LinkedHashMap<String,Object>();conflict.put("field",c.field());conflict.put("before",before);conflict.put("current",current.get(c.field()));conflict.put("attempted",after);conflicts.add(conflict);}
            next.put(c.field(),after);
        }
        if(!conflicts.isEmpty())return new Result(patch.id(),"conflict","同字段已被修改，请核对当前值后重新确认",conflicts,current);
        boolean changed=seen.stream().anyMatch(k->!same(current.get(k),next.get(k)));
        if(!changed)return new Result(patch.id(),"saved","没有新修改",List.of(),current);
        if(entity.equals("budget")&&(patch.reason()==null||patch.reason().isBlank()))throw invalid("预算修改须填写原因，保留独立版本");
        if(entity.equals("budget")) {
            if(next.get("calculationMode").equals("mold_formula")&&seen.contains("budgetAmount")&&next.get("budgetAmount")!=null)throw invalid("公式测算与手工上限不能混用；先清空手工金额或切换手工模式");
        } else {
            if(seen.contains("approvedAmount")||seen.contains("approvalStatus")||seen.contains("state")||current.get("sourceSystem").equals("erp")) access.requireFinanceConfirm();
            String source=current.get("sourceSystem").toString(),oldState=current.get("state").toString(),newState=next.get("state").toString();
            if(source.equals("erp")&&!Set.of("productLineId","itemId","moldSetId","budgetId","notes").containsAll(seen))throw invalid("ERP已过账明细原值及状态不可手工改写；冲销须保留新明细ID");
            if(source.equals("erp")&&(patch.reason()==null||patch.reason().isBlank()))throw invalid("ERP关系映射须填写核对依据，不能按金额猜测");
            if(!source.equals("erp")&&!oldState.equals("draft")&&seen.stream().anyMatch(k->!Set.of("state","productLineId","itemId","moldSetId","budgetId","notes").contains(k)))throw invalid("已确认费用只能作废或核对归属，金额原值保留");
            if(!oldState.equals(newState)&&!(oldState.equals("draft")&&(newState.equals("confirmed")||newState.equals("void"))||oldState.equals("confirmed")&&newState.equals("void")))throw invalid("费用状态不能回退");
            if(newState.equals("void")&&(patch.reason()==null||patch.reason().isBlank()))throw invalid("作废费用须填写原因");
            if(next.get("approvalStatus").equals("approved")&&next.get("approvalInstanceId")==null)throw invalid("审批通过须关联真实审批实例ID；申报/审批不等于ERP入账");
            if(next.get("approvedAmount")!=null&&!next.get("approvalStatus").equals("approved"))throw invalid("审批通过金额须与通过状态及审批ID一起维护");
            scope((Long)next.get("productLineId"),(Long)next.get("itemId"),(Long)next.get("moldSetId"));
            if(next.get("productId")!=null&&next.get("itemId")!=null&&jdbc.queryForObject("select count(*) from plm_collaboration_item_project where project_id=? and item_id=?",Long.class,next.get("productId"),next.get("itemId"))==0)throw invalid("历史项目未关联此协作档案，请先人工核对项目关联，不按金额转移费用");
            if(next.get("itemId")==null&&next.get("productLineId")==null&&next.get("productId")==null)throw invalid("请明确费用归属，不按金额匹配");
            validateBudget((Long)next.get("budgetId"),(Long)next.get("productLineId"),(Long)next.get("itemId"),(Long)next.get("moldSetId"),current.get("currencyCode").toString());
        }
        CurrentUser actor=access.actor();int version=entity.equals("budget")?((Number)current.get("versionNo")).intValue()+1:0;
        for(String key:seen) if(!same(current.get(key),next.get(key))) {
            Object value=next.get(key);if(value instanceof LocalDateTime date)value=Timestamp.valueOf(date);
            jdbc.update("update "+table(entity)+" set "+fields(entity).get(key)+"=? where "+idColumn(entity)+"=?",value,patch.id());
            history(entity,patch.id(),entity.equals("budget")?version:null,key,current.get(key),next.get(key),patch.reason(),actor);
        }
        if(entity.equals("budget")){jdbc.update("update plm_development_budget set version_no=? where budget_id=?",version,patch.id());history(entity,patch.id(),version,"__version",current,next,patch.reason(),actor);}
        else if(!same(current.get("state"),next.get("state"))){String prefix=next.get("state").equals("confirmed")?"confirmed":"voided";jdbc.update("update plm_project_cost_item set "+prefix+"_at=current_timestamp,"+prefix+"_by=? where project_cost_item_id=?",actor.username(),patch.id());}
        jdbc.update("update "+table(entity)+" set updated_at=current_timestamp,updated_by=? where "+idColumn(entity)+"=?",actor.username(),patch.id());
        log(entity,patch.id(),entity.equals("budget")?"DEVELOPMENT_BUDGET_UPDATE":"COST_ITEM_UPDATE",request);
        return new Result(patch.id(),"saved","已保存",List.of(),detail(entity,patch.id()));
    }
    public PageVO<Map<String,Object>> history(String entity,long id,int page,int size) {
        detail(entity,id);Long total=jdbc.queryForObject("select count(*) from plm_development_finance_history where entity_type=? and entity_id=?",Long.class,entity,id);
        var rows=jdbc.query("select *,before_value::text as before_json,after_value::text as after_json from plm_development_finance_history where entity_type=? and entity_id=? order by history_id desc limit ? offset ?",this::map,entity,id,size,(long)(page-1)*size);
        return new PageVO<>(rows,page,size,total==null?0:total,total==null?0:(total+size-1)/size);
    }
    void history(String entity,long id,Integer version,String field,Object before,Object after,String reason,CurrentUser actor) {
        jdbc.update("insert into plm_development_finance_history(entity_type,entity_id,version_no,field_name,before_value,after_value,reason,actor_id,actor_name) values(?,?,?,?,?::jsonb,?::jsonb,?,?,?)",entity,id,version,field,encode(before),encode(after),reason,actor.userId(),actor.username());
    }
    private void log(String entity,long id,String action,HttpServletRequest request){operationLog.logSuccess(OperationLogCreateCommand.builder().action(action).businessType(entity.equals("budget")?"DEVELOPMENT_BUDGET":"PROJECT_COST_ITEM").businessId(Long.toString(id)).detailJson("{\"entity\":\""+entity+"\",\"id\":"+id+"}").request(request).build());}
    String encode(Object value){try{return json.writeValueAsString(value);}catch(Exception e){throw invalid("数据无法序列化");}}
    Map<String,Object> map(ResultSet rs,int index)throws SQLException{
        Map<String,Object> row=new LinkedHashMap<>();var meta=rs.getMetaData();for(int n=1;n<=meta.getColumnCount();n++) {String key=com.yuewei.plm.module.collaboration.CollaborationRepository.camel(meta.getColumnLabel(n));Object value=rs.getObject(n);if(value instanceof Timestamp t)value=t.toLocalDateTime().toString();if(value instanceof java.sql.Date d)value=d.toLocalDate().toString();if(value instanceof OffsetDateTime d)value=d.toString();row.put(key,value);}
        calculate(row);if(row.containsKey("budgetKind"))row.put("remainingBudget",row.get("calculatedTotal")==null||row.get("erpPostedNet")==null?null:decimal(row.get("calculatedTotal")).subtract(decimal(row.get("erpPostedNet"))));return row;
    }
    public Map<String,Object> summary(String entity,Query query) {
        access.requireFinanceRead();Filter f=filter(entity,query);
        if(entity.equals("expense")) {var rows=jdbc.query("select e.currency_code,count(*) as record_count,sum(e.requested_amount) as requested_total,sum(e.approved_amount) as approved_total,sum(e.amount) filter(where e.status='confirmed' and e.source_system='manual') as declared_total,sum(e.erp_posted_amount) filter(where e.source_system='erp') as erp_posted_net,count(*) filter(where e.budget_id is null) as unmapped_count"+EXPENSE_FROM+f.where+" and e.status<>'void' group by e.currency_code order by e.currency_code",this::map,f.args.toArray());return Map.of("currencyGroups",rows,"rule","审批、申报与ERP入账分别展示；原币分组，冲销按稳定明细净额归集");}
        var rows=jdbc.query("select b.currency_code,b.budget_kind,count(*) as record_count,sum("+SQL_TOTAL+") as budget_total,count(*) filter(where ("+SQL_TOTAL+") is null) as unknown_count"+BUDGET_FROM+f.where+" group by b.currency_code,b.budget_kind order by b.currency_code,b.budget_kind",this::map,f.args.toArray());return Map.of("currencyGroups",rows,"rule","平台预算与模具预算独立展示，不相加；未知不当零，颜色项目不重复计入");
    }
    public List<Map<String,Object>> legacyItems(long productId){access.requireFinanceRead();access.requireProduct(productId);return jdbc.query(EXPENSE_SELECT+EXPENSE_FROM+" where e.deleted_flag=0 and e.product_id=? order by e.updated_at desc,e.project_cost_item_id desc",this::map,productId);}
    public Map<String,Object> legacyItem(long productId,long id){access.requireFinanceRead();access.requireProduct(productId);var row=detail("expense",id);if(!same(row.get("productId"),productId))throw invalid("费用不属于该项目");return row;}
    public Result transition(long productId,long id,String next,HttpServletRequest request){var row=legacyItem(productId,id);return save("expense",new Batch(List.of(new Patch(id,List.of(new Change("state",json.valueToTree(row.get("state")),json.valueToTree(next))),next.equals("void")?"旧项目入口作废费用":"旧项目入口确认费用"))),request).get(0);}
    public Result legacyUpdate(long productId,long id,Map<String,Object> values,LocalDateTime beforeUpdatedAt,HttpServletRequest request){
        if(beforeUpdatedAt==null)throw invalid("旧费用更新须携带上次返回的 updatedAt 作为 beforeUpdatedAt，请重新读取或使用 /development-expenses/batch-save 提交字段原值");
        var row=legacyItem(productId,id);LocalDateTime current=LocalDateTime.parse(row.get("updatedAt").toString());
        if(!beforeUpdatedAt.equals(current))throw invalid("费用已被修改，请重新读取 updatedAt 后核对，或使用 /development-expenses/batch-save；不会覆盖后续修改");
        List<Change> changes=values.entrySet().stream().map(e->new Change(e.getKey(),json.valueToTree(row.get(e.getKey())),json.valueToTree(e.getValue()))).toList();
        return save("expense",new Batch(List.of(new Patch(id,changes,"旧项目入口维护费用（已核对客户端更新时间）"))),request).get(0);
    }
    public ObjectMapper json(){return json;}
    public PilotAccessService access(){return access;}
    public JdbcTemplate jdbc(){return jdbc;}
    public PlatformTransactionManager transactionManager(){return transactionManager;}
}
