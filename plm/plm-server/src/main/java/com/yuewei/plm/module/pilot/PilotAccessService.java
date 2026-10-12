package com.yuewei.plm.module.pilot;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.common.security.CurrentUserContext;
import java.util.*;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

/** Server identity, explicit actions and object scopes; opt-in preserves legacy users. */
@Service @RequiredArgsConstructor
public class PilotAccessService {
 private final JdbcTemplate jdbc; private final ObjectMapper json;
 public static final Map<String,List<String>> ROLE_PERMISSIONS=Map.of(
  "administrator",List.of("*"),
  "domestic",List.of("dashboard:view","project:view","product:view","process:view","inventory:view","supplier:view","order:view","production-order:view","collaboration:view","pilot:tasks","schedule:read","schedule:write","schedule:remind","task:processing","task:testing","task:ship","task:arrival","task:acceptance","file:read","documents:write","documents:publish","bom:write","bom:publish","report:view"),
  "finance",List.of("dashboard:view","project:view","collaboration:view","pilot:tasks","schedule:read","finance:read","finance:write","finance:confirm","finance:export","file:read","report:view"),
  "supplier",List.of("pilot:tasks","task:processing","task:testing","task:ship","file:read"),
  "mexico",List.of("pilot:tasks","task:arrival","task:acceptance","file:read"));
 public record Access(CurrentUser actor,String role,List<String> permissions,boolean allObjects,boolean pilot) {}
 public Access access() {
  return access(com.yuewei.plm.common.security.CurrentUserResolver.resolve(jdbc));
 }
 private Access access(CurrentUser real) {
  List<Map<String,Object>> rows=jdbc.queryForList("select role_code,permissions::text permissions,all_objects from plm_pilot_account where user_id=?",real.userId());
  var r=rows.isEmpty()?Map.<String,Object>of():rows.get(0);boolean admin=real.allPermissions();
  boolean pilot=r.get("role_code")!=null;String role=admin?"administrator":Objects.toString(r.get("role_code"),"legacy");
  List<String> permissions;
  try {permissions=admin?List.of("*"):pilot?json.readValue(Objects.toString(r.get("permissions"),"[]"),new TypeReference<List<String>>(){}):List.of("collaboration:view");}
  catch(Exception e){throw new BusinessException(40103,"账号权限配置无效");}
  return new Access(real,role,List.copyOf(permissions),admin||!pilot||Boolean.TRUE.equals(r.get("all_objects")),pilot);
 }
 public com.yuewei.plm.module.auth.vo.CurrentUserVO userView(CurrentUser claimed) {
  var a=access(com.yuewei.plm.common.security.CurrentUserResolver.resolve(jdbc,claimed));
  var result=com.yuewei.plm.module.auth.vo.CurrentUserVO.from(a.actor());
  result.setPermissions(a.permissions());result.setRoleCode(a.role());
  result.setDepartmentName(jdbc.queryForObject("select department_name from sys_user where user_id=?",String.class,a.actor().userId()));
  return result;
 }
 public CurrentUser actor(){return access().actor();}
 public long actorId(){return actor().userId();}
 public boolean isPilot(){return access().pilot();}
 public boolean isRestricted(){var a=access();return a.pilot()&&!a.actor().allPermissions();}
 public boolean isExternal(){return Set.of("supplier","mexico").contains(access().role());}
 public boolean hasPermission(String permission){var a=access();return a.actor().allPermissions()||a.permissions().contains(permission);}
 public void requirePermission(String permission){if(!hasPermission(permission)) throw forbidden("没有权限："+permission);}
 public void requireAdministrator(){if(!actor().allPermissions()) throw forbidden("仅管理员可以维护真实账号与授权");}
 public void requireDomesticView(){if(isExternal()) throw forbidden("此账号仅可查看已分配的手机任务");}
 public void requireFinanceRead(){requirePermission("finance:read");}
 public void requireFinanceWrite(){requirePermission("finance:write");}
 public void requireFinanceConfirm(){requirePermission("finance:confirm");}
 public void requireFinanceExport(){requirePermission("finance:export");}
 public void requireItem(long id){requireObject("item",id);}
 public void requireMold(long id){requireObject("mold",id);}
 public void requireProduct(long id){requireObject("product",id);}
 public void requireBom(long id){
  requireDomesticView();if(id<1)throw forbidden("对象授权无效");
  Long product;
  try{product=jdbc.queryForObject("select product_id from plm_product_bom where product_bom_id=? and deleted_flag=0",Long.class,id);}
  catch(org.springframework.dao.EmptyResultDataAccessException missing){throw forbidden("对象不存在或未获授权");}
  if(product==null||product<1)throw forbidden("对象不存在或未获授权");requireProduct(product);
 }
 public void requireFile(long id){requirePermission("file:read");requireObject("file",id);}
 private void requireObject(String type,long id){
  if(id<1) throw forbidden("对象授权无效");
  String table=switch(type){case "item"->"plm_collaboration_item";case "mold"->"plm_collaboration_mold_set";case "product"->"plm_product";case "file"->"plm_attachment";default->throw new IllegalArgumentException("entityType");};
  String pk=switch(type){case "item"->"item_id";case "mold"->"mold_set_id";case "product"->"product_id";default->"attachment_id";};
  Long count=jdbc.queryForObject("select count(*) from "+table+" o where o."+pk+"=? and o.deleted_flag=0 and ("+visibleSqlClause(type,"o."+pk)+")",Long.class,id);
  if(count==null||count==0) throw forbidden("对象不存在或未获授权");
 }
 /** idExpression must be a trusted code-owned SQL identifier, never request input. */
 public String visibleSqlClause(String entityType,String idExpression){
  if(!idExpression.matches("[A-Za-z_][A-Za-z0-9_]*(\\.[A-Za-z_][A-Za-z0-9_]*)?")) throw new IllegalArgumentException("unsafe SQL identifier");
  var a=access();if(a.allObjects()) return "true";
  return scopeClause(entityType,idExpression,a.actor().userId());
 }
 private String scopeClause(String entityType,String idExpression,long uid){
  String direct="exists(select 1 from plm_pilot_scope ps where ps.user_id="+uid+" and ps.entity_type='"+entityType+"' and ps.entity_id="+idExpression+")";
  return switch(entityType){
   case "file" -> direct;
   case "item" -> "("+direct+" or exists(select 1 from plm_collaboration_mold_set ss join plm_pilot_scope ps on ps.entity_type='mold' and ps.entity_id=ss.mold_set_id and ps.user_id="+uid+" where ss.item_id="+idExpression+" and ss.deleted_flag=0) or exists(select 1 from plm_collaboration_item si join plm_pilot_scope ps on ps.entity_type='product' and ps.user_id="+uid+" and (ps.entity_id=si.product_line_id or exists(select 1 from plm_collaboration_item_project ip where ip.item_id=si.item_id and ip.project_id=ps.entity_id)) where si.item_id="+idExpression+"))";
   case "mold" -> "("+direct+" or exists(select 1 from plm_collaboration_mold_set si where si.mold_set_id="+idExpression+" and si.deleted_flag=0 and (exists(select 1 from plm_pilot_scope ps where ps.entity_type='item' and ps.entity_id=si.item_id and ps.user_id="+uid+") or exists(select 1 from plm_collaboration_item ci join plm_pilot_scope ps on ps.entity_type='product' and ps.user_id="+uid+" and (ps.entity_id=ci.product_line_id or exists(select 1 from plm_collaboration_item_project ip where ip.item_id=ci.item_id and ip.project_id=ps.entity_id)) where ci.item_id=si.item_id))))";
   case "product" -> "("+direct+" or exists(select 1 from plm_collaboration_item_project ip join plm_pilot_scope ps on ps.entity_type='item' and ps.entity_id=ip.item_id and ps.user_id="+uid+" where ip.project_id="+idExpression+"))";
   default -> throw new IllegalArgumentException("entityType");};
 }
 private static BusinessException forbidden(String message){return new BusinessException(40103,message);}
}
