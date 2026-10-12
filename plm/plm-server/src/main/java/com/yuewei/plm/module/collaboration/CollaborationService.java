package com.yuewei.plm.module.collaboration;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.common.security.CurrentUserContext;
import com.yuewei.plm.common.vo.PageVO;
import com.yuewei.plm.module.operationlog.service.OperationLogCreateCommand;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import jakarta.servlet.http.HttpServletRequest;
import java.time.LocalDate;
import java.util.*;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

import static com.yuewei.plm.module.collaboration.CollaborationTypes.*;
import static com.yuewei.plm.module.collaboration.CollaborationFields.*;

@Service
@RequiredArgsConstructor
public class CollaborationService {
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    private final CollaborationRepository repository;
    private final org.springframework.transaction.PlatformTransactionManager transactionManager;
    private final OperationLogService operationLog;

    CurrentUser actor() {
        return com.yuewei.plm.common.security.CurrentUserResolver.resolve(jdbc);
    }
    Set<String> groups(CurrentUser actor) {
        if(actor.allPermissions()) return new LinkedHashSet<>(GROUPS);
        return new LinkedHashSet<>(jdbc.queryForList("select field_group from plm_collaboration_assignment where user_id=?",String.class,actor.userId()));
    }
    void requireGroup(CurrentUser actor,String group) {
        if(!groups(actor).contains(group)) throw new BusinessException(40103,"没有该字段组的填写权限："+group);
    }
    private void admin(CurrentUser actor) {if(!actor.allPermissions()) throw new BusinessException(40103,"仅管理员可以配置协作职责");}
    public PageVO<Map<String,Object>> page(Query query) {query.setMoldLedger(query.getView().equals("delivery"));return repository.page(query,groups(actor()));}
    public PageVO<Map<String,Object>> moldPage(Query query) {query.setView("delivery");query.setMoldLedger(true);return repository.page(query,groups(actor()));}
    public Map<String,Object> mold(long id) {actor();return repository.row("mold_set",id);}
    public Map<String,Object> moldOptions() {
        return options();
    }
    public List<Map<String,Object>> inventoryOptions(String keyword) {actor();return repository.moldInventoryOptions(keyword);}
    public PageVO<Map<String,Object>> moldHistory(long id,int page,int size) {actor();return repository.moldHistory(id,page,size);}
    public Map<String,Object> moldReferences(long id) {Map<String,Object> mold=mold(id);return references(((Number)mold.get("itemId")).longValue());}
    public Map<String,Object> copyMold(long id,CreateMoldSet dto,HttpServletRequest request) {
        Map<String,Object> source=mold(id);
        return createMoldSet(((Number)source.get("itemId")).longValue(),new CreateMoldSet(dto.setName(),null,null,id),request);
    }
    public Map<String,Object> options() {
        CurrentUser actor=actor();Set<String> allowed=groups(actor);
        return Map.of("productLines",repository.productLines(),"itemFields",ITEM,"moldFields",MOLD,
            "writableGroups",allowed,"administrator",actor.allPermissions(),"userId",actor.userId(),
            "users",repository.users().stream().map(u->Map.of("userId",u.get("userId"),"username",u.get("username"),"displayName",Objects.toString(u.get("displayName"),u.get("username").toString()))).toList());
    }
    public Map<String,Object> item(long id) {actor();return repository.row("item",id);}
    public Map<String,Object> references(long id) {actor();return repository.references(id);}
    public PageVO<Map<String,Object>> history(long id,int page,int size) {actor();return repository.history(id,page,size);}
    public List<Map<String,Object>> projectOptions(Long line,String keyword) {actor();return repository.projectOptions(line,keyword);}
    public List<Map<String,Object>> moldCodes(Long item,String keyword) {actor();return repository.moldCodes(item,keyword);}

    public Map<String,Object> createItem(CreateItem dto,HttpServletRequest request) {
        CurrentUser actor=actor();requireGroup(actor,"market");
        return new TransactionTemplate(transactionManager).execute(tx-> {
            String style=Objects.toString(normalise(field("item","styleName"),json.valueToTree(dto.styleName())),"");
            String model=Objects.toString(normalise(field("item","compatibleModels"),json.valueToTree(dto.compatibleModels())),"");
            Object code=normalise(field("item","phoneModelCode"),json.valueToTree(dto.phoneModelCode()));
            Object brand=normalise(field("item","brand"),json.valueToTree(dto.brand()));
            Object phonePrice=normalise(field("item","phonePrice"),json.valueToTree(dto.phonePrice()));
            Object priceCurrency=normalise(field("item","priceCurrency"),json.valueToTree(dto.priceCurrency()));
            Object salesPlatform=normalise(field("item","salesPlatform"),json.valueToTree(dto.salesPlatform()));
            Object referenceUrl=normalise(field("item","referenceUrl"),json.valueToTree(dto.referenceUrl()));
            Object notes=normalise(field("item","notes"),json.valueToTree(dto.notes()));
            if(brand==null) brand=brandFromModel(model);
            validateLine(dto.productLineId());validatePhoneCode(code);
            lockIdentity(style,model);
            Long count=jdbc.queryForObject("select count(*) from plm_collaboration_item where deleted_flag=0 and lower(btrim(style_name))=lower(?) and lower(btrim(compatible_models))=lower(?)",Long.class,style,model);
            if(count!=null&&count>0) throw invalid("该款式与型号已有协作档案，请关联原档案；复制模具请新增模具套");
            Long id=jdbc.queryForObject("""
                insert into plm_collaboration_item(product_line_id,style_name,brand,compatible_models,phone_model_code,
                  phone_price,price_currency,sales_platform,reference_url,notes,created_by,updated_by)
                values(?,?,?,?,?,?,?,?,?,?,?,?) returning item_id
                """,Long.class,dto.productLineId(),style,brand,model,code,phonePrice,priceCurrency,
                salesPlatform,referenceUrl,notes,actor.username(),actor.username());
            Map<String,Object> row=repository.row("item",id);
            history(actor,id,"item",id,"__created",null,row,"新增协作档案");
            log(actor,id,"COLLABORATION_CREATE",row,request);return row;
        });
    }
    public Map<String,Object> createMoldSet(long itemId,CreateMoldSet dto,HttpServletRequest request) {
        CurrentUser actor=actor();requireGroup(actor,"engineering");
        return new TransactionTemplate(transactionManager).execute(tx-> {
            lock("item",itemId);
            Map<String,Object> source=null;
            Long pcCode=dto.pcMoldCodeId(),tpuCode=dto.tpuMoldCodeId();
            if(dto.sourceMoldSetId()!=null) {
                lock("mold_set",dto.sourceMoldSetId());source=repository.row("mold_set",dto.sourceMoldSetId());
                if(!same(source.get("itemId"),itemId)) throw invalid("复制来源必须属于同一款式与兼容型号档案");
                pcCode=(Long)source.get("pcMoldCodeId");tpuCode=(Long)source.get("tpuMoldCodeId");
            }
            validateMoldCode(itemId,pcCode);validateMoldCode(itemId,tpuCode);
            Integer setNo=jdbc.queryForObject("select coalesce(max(set_no),0)+1 from plm_collaboration_mold_set where item_id=?",Integer.class,itemId);
            String name=dto.setName()==null||dto.setName().isBlank()?"第 "+setNo+" 套"+(setNo>1?"（复制 / 重新开模）":""):dto.setName().trim();
            normalise(field("mold_set","setName"),json.valueToTree(name));
            Long id=jdbc.queryForObject("insert into plm_collaboration_mold_set(item_id,set_no,set_name,source_mold_set_id,created_by,updated_by) values(?,?,?,?,?,?) returning mold_set_id",Long.class,itemId,setNo,name,dto.sourceMoldSetId(),actor.username(),actor.username());
            for(String part:List.of("PC","TPU")) {
                String prefix=part.equals("PC")?"pc":"tpu";
                jdbc.update("insert into plm_collaboration_mold_part(mold_set_id,part_type,product_mold_code_id,original_mold_code,inventory_id) values(?,?,?,?,?)",id,part,part.equals("PC")?pcCode:tpuCode,source==null?null:source.get(prefix+"OriginalMoldCode"),source==null?null:source.get(prefix+"InventoryId"));
            }
            Map<String,Object> row=repository.row("mold_set",id);
            history(actor,itemId,"mold_set",id,"__created",null,row,source==null?"新增 PC＋TPU 模具套":"复制原套编码关联，新增独立实物套次；日期、位置、验收不复制");
            log(actor,itemId,"COLLABORATION_MOLD_CREATE",row,request);return row;
        });
    }
    public List<RowResult> save(BatchSave dto,HttpServletRequest request) {
        CurrentUser actor=actor();Set<String> allowed=groups(actor);List<RowResult> results=new ArrayList<>();
        for(RowPatch row:dto.rows()) {
            try {results.add(new TransactionTemplate(transactionManager).execute(tx->saveRow(actor,allowed,row,request)));}
            catch(BusinessException e) {results.add(new RowResult(row.entityType(),row.id(),e.getCode()==40103?"forbidden":"invalid",e.getMessage(),List.of(),null));}
            catch(org.springframework.dao.DataIntegrityViolationException e) {results.add(new RowResult(row.entityType(),row.id(),"invalid","关联或数据约束冲突，请刷新核对",List.of(),null));}
        }
        return results;
    }
    private RowResult saveRow(CurrentUser actor,Set<String> allowed,RowPatch patch,HttpServletRequest request) {
        lock(patch.entityType(),patch.id());Map<String,Object> current=repository.row(patch.entityType(),patch.id());
        long itemId=((Number)current.get("itemId")).longValue();
        Map<String,Object> next=new LinkedHashMap<>(current);List<Map<String,Object>> conflicts=new ArrayList<>();
        Set<String> seen=new HashSet<>();String reason="";
        for(CellChange change:patch.changes()) {
            Field f=field(patch.entityType(),change.field());
            if(!seen.add(f.key())) throw invalid("同一字段不能重复提交");
            if(!allowed.contains(f.group())) throw new BusinessException(40103,"没有填写权限："+f.label());
            Object before=normalise(f,change.before());Object after=normalise(f,change.after());
            if(!same(current.get(f.key()),before)) {
                Map<String,Object> conflict=new LinkedHashMap<>();conflict.put("field",f.key());conflict.put("label",f.label());
                conflict.put("before",before);conflict.put("current",current.get(f.key()));conflict.put("attempted",after);conflicts.add(conflict);
            }
            if((f.kind().equals("part_status")||f.kind().equals("acceptance"))&&after==null) throw invalid(f.label()+"不能为空");
            if(change.reason()!=null&&!change.reason().isBlank()) reason=change.reason().trim();
            next.put(f.key(),after);
        }
        if(!conflicts.isEmpty()) return new RowResult(patch.entityType(),patch.id(),"conflict","此行已被他人修改，请核对后重新确认",conflicts,current);
        for(CellChange change:patch.changes()) {
            Field f=field(patch.entityType(),change.field());Object after=next.get(f.key());
            if(f.kind().equals("count") && current.get(f.key())!=null &&
                (after==null || ((Number)after).longValue()<((Number)current.get(f.key())).longValue()) &&
                (change.reason()==null||change.reason().isBlank())) throw invalid("下调或清空累计产量须填写更正原因");
        }
        if(patch.entityType().equals("item")) {
            validateLine((Long)next.get("productLineId"));
            if(seen.contains("styleName")||seen.contains("compatibleModels")) {
                lockIdentity(next.get("styleName").toString(),next.get("compatibleModels").toString());
                Long duplicates=jdbc.queryForObject("select count(*) from plm_collaboration_item where deleted_flag=0 and item_id<>? and lower(btrim(style_name))=lower(?) and lower(btrim(compatible_models))=lower(?)",Long.class,patch.id(),next.get("styleName"),next.get("compatibleModels"));
                if(duplicates!=null&&duplicates>0) throw invalid("该款式与型号已有协作档案，请核对原档案，不重复汇总产量");
            }
            if(seen.contains("phoneModelCode")&&!same(current.get("phoneModelCode"),next.get("phoneModelCode"))) validatePhoneCode(next.get("phoneModelCode"));
            if(((Number)current.get("projectCount")).longValue()>0 &&
                (!same(current.get("productLineId"),next.get("productLineId"))||!same(current.get("phoneModelCode"),next.get("phoneModelCode"))))
                throw invalid("已关联项目的产品线和型号编码不能直接改动，请先核对项目关联");
            if(next.get("phonePrice")!=null && next.get("priceCurrency")==null) throw invalid("填写价格时请选择币种，无法确定请选“待确认”");
        } else {
            List<String> warnings=dateWarnings(next);
            if(!warnings.isEmpty()&&reason.isBlank()) throw invalid(String.join("；",warnings)+"。请修正日期或填写核对说明");
            validateMoldCode(itemId,(Long)next.get("pcMoldCodeId"));validateMoldCode(itemId,(Long)next.get("tpuMoldCodeId"));
            if(seen.contains("ownerUserId")&&!same(current.get("ownerUserId"),next.get("ownerUserId"))&&next.get("ownerUserId")!=null) {
                if(jdbc.queryForObject("select count(*) from sys_user where user_id=? and deleted_flag=0 and status='active'",Long.class,next.get("ownerUserId"))==0) throw invalid("请选择有效账号作为模具负责人");
            }
            validateParts(current,next,patch.changes());
            MoldScheduleTypes.validate(current,next,patch.changes());
            for(String key:List.of("logisticsOwnerUserId","mexicoOwnerUserId","productionOwnerUserId")) {
                if(seen.contains(key)&&next.get(key)!=null&&jdbc.queryForObject("select count(*) from sys_user where user_id=? and deleted_flag=0 and status='active'",Long.class,next.get(key))==0) throw invalid("请选择有效账号作为排程负责人");
            }
        }
        // A part is updated atomically: acceptance constraints must see the final dates/result,
        // regardless of the order of fields in a clipboard or import payload.
        if(patch.entityType().equals("mold_set")) for(String prefix:List.of("pc","tpu")) {
            List<Field> changed=patch.changes().stream().map(c->field("mold_set",c.field()))
                .filter(f->partField(f)&&f.key().startsWith(prefix)&&!same(current.get(f.key()),next.get(f.key()))).toList();
            if(!changed.isEmpty()) {
                List<Object> args=new ArrayList<>();changed.forEach(f->args.add(sqlValue(next.get(f.key()))));args.add(patch.id());args.add(prefix.toUpperCase(Locale.ROOT));
                jdbc.update("update plm_collaboration_mold_part set "+String.join(",",changed.stream().map(f->f.column()+"=?").toList())+" where mold_set_id=? and part_type=?",args.toArray());
            }
        }
        for(CellChange change:patch.changes()) {
            Field f=field(patch.entityType(),change.field());Object value=next.get(f.key());
            if(same(current.get(f.key()),value)) continue;
            if(!(patch.entityType().equals("mold_set")&&partField(f))) jdbc.update("update "+table(patch.entityType())+" set "+f.column()+"=? where "+idColumn(patch.entityType())+"=?",sqlValue(value),patch.id());
            history(actor,itemId,patch.entityType(),patch.id(),f.key(),current.get(f.key()),value,change.reason());
        }
        // Explicit arrival-plan confirmation captures the basis even when the entered date is unchanged.
        if(patch.entityType().equals("mold_set")&&seen.contains("plannedFactoryArrivalDate")) {
            Object basis=next.get("plannedFactoryArrivalDate")==null?null:next.get("plannedMoldDeliveryDate");
            jdbc.update("update plm_collaboration_mold_set set arrival_confirmed_basis_date=? where mold_set_id=?",basis==null?null:java.sql.Date.valueOf(parseDate(basis.toString())),patch.id());
            if(!same(current.get("arrivalConfirmedBasisDate"),basis)) history(actor,itemId,"mold_set",patch.id(),"arrivalConfirmedBasisDate",current.get("arrivalConfirmedBasisDate"),basis,"负责人确认到厂计划");
        }
        jdbc.update("update "+table(patch.entityType())+" set updated_at=now(),updated_by=? where "+idColumn(patch.entityType())+"=?",actor.username(),patch.id());
        log(actor,itemId,"COLLABORATION_UPDATE",patch,request);
        return new RowResult(patch.entityType(),patch.id(),"saved","已保存",List.of(),repository.row(patch.entityType(),patch.id()));
    }
    private void validateParts(Map<String,Object> current,Map<String,Object> next,List<CellChange> changes) {
        for(String prefix:List.of("pc","tpu")) {
            String status=Objects.toString(next.get(prefix+"AcceptanceStatus"),"pending");
            Object arrived=next.get(prefix+"FactoryArrivalDate"),accepted=next.get(prefix+"AcceptanceDate");
            String part=prefix.equals("pc")?"PC":"TPU";
            if(status.equals("passed")&&(arrived==null||accepted==null)) throw invalid(part+" 验收通过须填写实际到厂日期和验收日期");
            if(arrived!=null&&accepted!=null&&parseDate(accepted.toString()).isBefore(parseDate(arrived.toString()))) throw invalid(part+" 验收日期不能早于实际到厂日期");
            if(status.equals("failed")&&(next.get(prefix+"AcceptanceIssues")==null||next.get(prefix+"AcceptanceIssues").toString().isBlank())) throw invalid(part+" 验收不通过须填写问题说明");
            Object masterId=next.get(prefix+"MoldCodeId"),raw=next.get(prefix+"OriginalMoldCode"),inventoryId=next.get(prefix+"InventoryId");
            String masterCode=null;
            if(masterId!=null) masterCode=jdbc.queryForObject("select mold_code from plm_product_mold_code where product_mold_code_id=?",String.class,masterId);
            if(masterCode!=null&&raw!=null&&!masterCode.equals(raw.toString())) throw invalid(part+" 原模具编码与所选编码资料不一致，请保留来源原值");
            if(inventoryId!=null) {
                List<String> codes=jdbc.queryForList("select inventory_code from plm_inventory where inventory_id=? and deleted_flag=0",String.class,inventoryId);
                if(codes.isEmpty()) throw invalid(part+" 历史库存资料不存在");
                String effective=masterCode!=null?masterCode:Objects.toString(raw,null);
                if(!codes.get(0).equals(effective)) throw invalid(part+" 原模具编码须与人工选择的库存资料原码一致");
            }
            if(!same(current.get(prefix+"InventoryId"),inventoryId)&&changes.stream().filter(c->c.field().equals(prefix+"InventoryId")).noneMatch(c->c.reason()!=null&&!c.reason().isBlank()))
                throw invalid(part+" 库存资料关联须填写人工核对说明；不能按库存分类或数量自动建模具");
        }
    }
    public Map<String,Object> linkProjects(long itemId,LinkProjects dto,HttpServletRequest request) {
        CurrentUser actor=actor();requireGroup(actor,"market");
        return new TransactionTemplate(transactionManager).execute(tx-> {
            lock("item",itemId);Map<String,Object> item=repository.row("item",itemId);
            List<Long> currentIds=((List<Map<String,Object>>)item.get("projects")).stream().map(p->((Number)p.get("projectId")).longValue()).sorted().toList();
            if(!dto.append() && (dto.beforeProjectIds()==null || !currentIds.equals(dto.beforeProjectIds().stream().distinct().sorted().toList())))
                throw invalid("项目关联已被其他人修改，请重新打开并核对");
            Set<Long> selected=new LinkedHashSet<>();if(dto.append()) selected.addAll(currentIds);selected.addAll(dto.projectIds());
            List<Long> ids=List.copyOf(selected);
            for(Long id:ids) {
                List<Map<String,Object>> rows=jdbc.queryForList("select parent_product_id,model,phone_model_code from plm_product where product_id=? and product_type='model_variant' and deleted_flag=0",id);
                if(rows.isEmpty()) throw invalid("只能关联已有型号项目");Map<String,Object> project=rows.get(0);
                if(!same(item.get("productLineId"),project.get("parent_product_id"))) throw invalid("项目所属产品线与协作档案不一致");
                boolean exact=Objects.toString(item.get("compatibleModels"),"").trim().equalsIgnoreCase(Objects.toString(project.get("model"),"").trim());
                if(!exact&&!dto.confirmCompatibility()) throw invalid("型号名称不一致，请人工确认兼容关系");
                List<Long> owners=jdbc.queryForList("select item_id from plm_collaboration_item_project where project_id=?",Long.class,id);
                if(!owners.isEmpty()&&!owners.get(0).equals(itemId)) throw invalid("该项目已关联其他协作档案，不能自动转移");
            }
            Object before=item.get("projects");
            jdbc.update("delete from plm_collaboration_item_project where item_id=?",itemId);
            for(Long id:ids) jdbc.update("insert into plm_collaboration_item_project(item_id,project_id,linked_by) values(?,?,?)",itemId,id,actor.username());
            jdbc.update("update plm_collaboration_item set updated_at=now(),updated_by=? where item_id=?",actor.username(),itemId);
            history(actor,itemId,"item",itemId,"projects",before,ids,"人工确认项目关联");
            log(actor,itemId,"COLLABORATION_LINK",ids,request);return repository.row("item",itemId);
        });
    }
    public Map<String,Object> assignments() {
        CurrentUser actor=actor();admin(actor);
        return Map.of("groups",assignmentMap(),"users",repository.users());
    }
    public List<Map<String,Object>> accounts() {admin(actor());return repository.users();}
    public Map<String,Object> initialiseExplicitBrands(HttpServletRequest request) {
        admin(actor());List<RowPatch> changes=new ArrayList<>();
        for(Map<String,Object> row:repository.previewRows("item")) {
            if(row.get("brand")!=null) continue;String brand=brandFromModel(Objects.toString(row.get("compatibleModels"),null));
            if(brand!=null) changes.add(new RowPatch("item",((Number)row.get("itemId")).longValue(),List.of(new CellChange("brand",json.nullNode(),json.valueToTree(brand),"根据型号名称中的明确品牌初始化；不改动已有品牌或历史项目"))));
        }
        List<RowResult> results=changes.isEmpty()?List.of():save(new BatchSave(changes),request);
        return Map.of("updated",results.stream().filter(r->r.status().equals("saved")).count(),"notSaved",results.stream().filter(r->!r.status().equals("saved")).count());
    }
    private Map<String,List<Long>> assignmentMap() {
        Map<String,List<Long>> assignments=new LinkedHashMap<>();GROUPS.forEach(g->assignments.put(g,new ArrayList<>()));
        jdbc.queryForList("select field_group,user_id from plm_collaboration_assignment order by field_group,user_id")
            .forEach(row->assignments.get(row.get("field_group").toString()).add(((Number)row.get("user_id")).longValue()));
        return assignments;
    }
    public Map<String,Object> saveAssignments(Assignments dto,HttpServletRequest request) {
        CurrentUser actor=actor();admin(actor);
        return new TransactionTemplate(transactionManager).execute(tx-> {
            jdbc.queryForObject("select pg_advisory_xact_lock(610091001)",(rs,n)->true);
            Map<String,List<Long>> before=assignmentMap();
            if(!normalAssignment(before).equals(normalAssignment(dto.before()))) throw invalid("职责配置已被其他管理员修改，请刷新后重新配置");
            Map<String,List<Long>> next=normalAssignment(dto.groups());
            Set<Long> active=new HashSet<>(repository.users().stream().map(u->((Number)u.get("userId")).longValue()).toList());
            if(next.values().stream().flatMap(List::stream).anyMatch(id->!active.contains(id))) throw invalid("只能分配给有效的真实账号");
            Set<Long> changedUsers=new TreeSet<>();
            for(String group:GROUPS) {
                Set<Long> previous=new HashSet<>(before.getOrDefault(group,List.of())),current=new HashSet<>(next.get(group));
                previous.stream().filter(id->!current.contains(id)).forEach(changedUsers::add);
                current.stream().filter(id->!previous.contains(id)).forEach(changedUsers::add);
            }
            jdbc.update("delete from plm_collaboration_assignment");
            next.forEach((g,ids)->ids.forEach(id->jdbc.update("insert into plm_collaboration_assignment(field_group,user_id) values(?,?)",g,id)));
            if(!changedUsers.isEmpty()) {
                List<Object> arguments=new ArrayList<>();arguments.add(actor.username());arguments.addAll(changedUsers);
                jdbc.update("update plm_pilot_account set version_no=version_no+1,updated_at=now(),updated_by=? where user_id in ("+
                    String.join(",",Collections.nCopies(changedUsers.size(),"?"))+")",arguments.toArray());
            }
            log(actor,0,"COLLABORATION_ASSIGNMENTS",Map.of("before",before,"after",next),request);
            return Map.of("groups",next,"users",repository.users());
        });
    }
    private Map<String,List<Long>> normalAssignment(Map<String,List<Long>> input) {
        if(input.keySet().stream().anyMatch(g->!GROUPS.contains(g))) throw invalid("未知字段组");
        Map<String,List<Long>> out=new LinkedHashMap<>();
        for(String group:GROUPS) {List<Long> ids=input.getOrDefault(group,List.of());if(ids==null||ids.size()>100) throw invalid("账号列表无效");out.put(group,ids.stream().filter(Objects::nonNull).distinct().sorted().toList());}
        return out;
    }
    private void validateLine(Long line) {
        if(line!=null&&jdbc.queryForObject("select count(*) from plm_product where product_id=? and deleted_flag=0 and product_type='product_line'",Long.class,line)==0) throw invalid("产品线不存在");
    }
    private void lockIdentity(String style,String models) {
        jdbc.queryForObject("select pg_advisory_xact_lock(hashtextextended(lower(btrim(?)) || chr(31) || lower(btrim(?)),610091002))",(rs,n)->true,style,models);
    }
    private void validatePhoneCode(Object code) {
        if(code!=null&&jdbc.queryForObject("select count(*) from plm_code_item where code_type='phone_model' and code_value=? and deleted_flag=0 and status='enabled'",Long.class,code.toString())==0) throw invalid("请选择已启用的手机型号编码，历史核对关系不能直接使用");
    }
    private void validateMoldCode(long itemId,Long codeId) {
        if(codeId==null) return;
        Long count=jdbc.queryForObject("""
            select count(*) from plm_product_mold_code mc where mc.product_mold_code_id=? and mc.deleted_flag=0
             and (exists(select 1 from plm_collaboration_item_project ip where ip.item_id=? and ip.project_id=mc.product_id)
               or mc.product_id=(select product_line_id from plm_collaboration_item where item_id=?))
            """,Long.class,codeId,itemId,itemId);
        if(count==null||count==0) throw invalid("模具编码不属于已关联项目或产品线");
    }
    private void lock(String entity,long id) {
        fields(entity);
        List<Long> ids=jdbc.queryForList("select "+idColumn(entity)+" from "+table(entity)+" where "+idColumn(entity)+"=? and deleted_flag=0 for update",Long.class,id);
        if(ids.isEmpty()) throw new BusinessException(40401,"协作记录不存在");
    }
    private static String table(String entity) {return "item".equals(entity)?"plm_collaboration_item":"plm_collaboration_mold_set";}
    private static String idColumn(String entity) {return "item".equals(entity)?"item_id":"mold_set_id";}
    private static Object sqlValue(Object value) {return value instanceof LocalDate d?java.sql.Date.valueOf(d):value;}
    private void history(CurrentUser actor,long itemId,String entity,long id,String field,Object before,Object after,String reason) {
        jdbc.update("insert into plm_collaboration_history(item_id,entity_type,entity_id,field_name,before_value,after_value,reason,actor_id,actor_name) values(?,?,?,?,?::jsonb,?::jsonb,?,?,?)",itemId,entity,id,field,encode(before),encode(after),reason,actor.userId(),actor.username());
    }
    private String encode(Object value) {try{return json.writeValueAsString(value);}catch(Exception e){throw new IllegalStateException("Cannot encode audit value",e);}}
    private void log(CurrentUser actor,long itemId,String action,Object data,HttpServletRequest request) {
        operationLog.logSuccess(OperationLogCreateCommand.builder().action(action).businessType("COLLABORATION")
            .businessId(String.valueOf(itemId)).businessName("协作计划").detailJson(encode(data)).request(request).build());
    }
}
