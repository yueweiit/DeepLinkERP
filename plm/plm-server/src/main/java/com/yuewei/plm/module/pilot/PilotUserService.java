package com.yuewei.plm.module.pilot;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.module.operationlog.service.*;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.constraints.*;
import java.util.*;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service @RequiredArgsConstructor
public class PilotUserService {
 private final JdbcTemplate jdbc;private final ObjectMapper json;private final PilotAccessService access;
 private final PasswordEncoder encoder;private final OperationLogService logs;
 public record Scope(@Pattern(regexp="item|mold|product|file") String entityType,@Positive long entityId){}
 public record UserInput(@NotBlank @Pattern(regexp="[A-Za-z0-9_.@-]{3,64}") String username,
  @NotBlank @Size(max=64) String displayName,@NotBlank @Size(max=64) String departmentName,
  @Pattern(regexp="administrator|domestic|finance|supplier|mexico") String roleCode,
  @Pattern(regexp="active|inactive") String status,boolean allObjects,
  @Size(max=128) String dingtalkUserId,@Size(max=40) List<String> permissions,
  @Size(max=5) List<String> fieldGroups,@Size(max=1000) List<@jakarta.validation.Valid Scope> scopes,
  @JsonProperty(access=JsonProperty.Access.WRITE_ONLY) @Size(max=128) String password,
  @Positive Long beforeVersion){}
 public List<Map<String,Object>> users(){
  access.requireAdministrator();
  Map<Long,List<Map<String,Object>>> scopes=new HashMap<>();
  for(var row:jdbc.queryForList("select user_id,entity_type \"entityType\",entity_id \"entityId\" from plm_pilot_scope order by user_id,entity_type,entity_id")){long id=((Number)row.remove("user_id")).longValue();scopes.computeIfAbsent(id,k->new ArrayList<>()).add(row);}
  Map<Long,List<String>> groups=new HashMap<>();
  for(var row:jdbc.queryForList("select user_id,field_group from plm_collaboration_assignment order by user_id,field_group"))groups.computeIfAbsent(((Number)row.get("user_id")).longValue(),k->new ArrayList<>()).add(row.get("field_group").toString());
  List<Map<String,Object>> result=new ArrayList<>();
  for(var row:jdbc.queryForList("select u.user_id \"userId\",u.username,u.display_name \"displayName\",u.department_name \"departmentName\",u.status,u.all_permissions \"allPermissions\",p.role_code \"roleCode\",p.all_objects \"allObjects\",p.dingtalk_user_id \"dingtalkUserId\",p.permissions::text \"permissionsJson\",p.version_no \"version\" from sys_user u left join plm_pilot_account p on p.user_id=u.user_id where u.deleted_flag=0 order by u.user_id")){
   long id=((Number)row.get("userId")).longValue();row.put("permissions",readList(Objects.toString(row.remove("permissionsJson"),"[]")));row.put("scopes",scopes.getOrDefault(id,List.of()));row.put("fieldGroups",groups.getOrDefault(id,List.of()));result.add(row);
  }return result;
 }
 public List<Map<String,Object>> roles(){access.requireAdministrator();return PilotAccessService.ROLE_PERMISSIONS.entrySet().stream().sorted(Map.Entry.comparingByKey()).map(r->Map.<String,Object>of("roleCode",r.getKey(),"permissions",r.getValue())).toList();}
 public List<Map<String,Object>> scopeOptions(String type,String keyword){access.requireAdministrator();if(!Set.of("item","mold","product","file").contains(type))throw invalid("授权对象类型无效");String select=switch(type){case "item"->"select item_id id,style_name||' / '||compatible_models label from plm_collaboration_item where deleted_flag=0";case "mold"->"select mold_set_id id,'MS-'||mold_set_id||' / '||set_name label from plm_collaboration_mold_set where deleted_flag=0";case "product"->"select product_id id,product_code||' / '||product_name label from plm_product where deleted_flag=0";default->"select attachment_id id,original_file_name label from plm_attachment where deleted_flag=0";};return jdbc.queryForList("select * from ("+select+") x where lower(coalesce(label,'')) like ? order by id desc limit 100","%"+Objects.toString(keyword,"").trim().toLowerCase(Locale.ROOT)+"%");}
 @Transactional public Map<String,Object> save(Long id,UserInput input,HttpServletRequest request){
  access.requireAdministrator();var actor=access.actor();String role=Objects.requireNonNullElse(input.roleCode(),"domestic");
  // Both account grants and the shared responsibility editor mutate the same memberships.
  jdbc.queryForObject("select pg_advisory_xact_lock(610091001)",(rs,n)->true);
  if(id!=null)jdbc.queryForList("select user_id from sys_user where deleted_flag=0 and all_permissions=true order by user_id for update");
  Map<String,Object> before=new LinkedHashMap<>();
  if(id!=null){var old=jdbc.queryForList("select u.display_name \"displayName\",u.department_name \"departmentName\",u.status,u.all_permissions \"allPermissions\",p.role_code role,p.permissions::text \"permissionsJson\",p.all_objects \"allObjects\",p.dingtalk_user_id \"dingtalkUserId\",p.version_no version from sys_user u left join plm_pilot_account p on p.user_id=u.user_id where u.user_id=?",id);if(!old.isEmpty()){before.putAll(old.get(0));before.put("permissions",readList(Objects.toString(before.remove("permissionsJson"),"[]")));}before.put("scopes",jdbc.queryForList("select entity_type \"entityType\",entity_id \"entityId\" from plm_pilot_scope where user_id=? order by entity_type,entity_id",id));before.put("fieldGroups",jdbc.queryForList("select field_group from plm_collaboration_assignment where user_id=? order by field_group",String.class,id));}
  if(!PilotAccessService.ROLE_PERMISSIONS.containsKey(role))throw invalid("试点角色无效");
  var permissions=input.permissions()==null?PilotAccessService.ROLE_PERMISSIONS.get(role):List.copyOf(new LinkedHashSet<>(input.permissions()));
  if(!PilotAccessService.ROLE_PERMISSIONS.get(role).containsAll(permissions)) throw invalid("权限超出固定角色范围");
  if(Set.of("supplier","mexico").contains(role)&&input.allObjects())throw invalid("外部账号必须逐对象授权");
  boolean admin=role.equals("administrator");String status=Objects.requireNonNullElse(input.status(),"active");
  if(id!=null){var old=jdbc.queryForList("select u.username,u.all_permissions,p.version_no from sys_user u left join plm_pilot_account p on p.user_id=u.user_id where u.user_id=? and u.deleted_flag=0 for update of u",id);if(old.isEmpty())throw invalid("账号不存在");if(!input.username().equals(old.get(0).get("username")))throw invalid("登录账号创建后不能修改");Object version=old.get(0).get("version_no");if(version!=null&&(input.beforeVersion()==null||((Number)version).longValue()!=input.beforeVersion()))throw new BusinessException(40901,"账号授权已变更，请刷新后核对");if(Boolean.TRUE.equals(old.get(0).get("all_permissions"))&&(!admin||status.equals("inactive"))){Long count=jdbc.queryForObject("select count(*) from sys_user where deleted_flag=0 and status='active' and all_permissions=true",Long.class);if(count==null||count<=1)throw invalid("不能停用或降权最后一位管理员");}}
  if(id==null&&(input.password()==null||input.password().length()<12))throw invalid("新账号须设置至少12位密码");
  if(input.password()!=null&&!input.password().isBlank()&&input.password().length()<12)throw invalid("新密码须至少12位");
  List<Scope> scopes=input.scopes()==null?List.of():input.scopes();for(Scope s:scopes){String sql=switch(s.entityType()){case "item"->"select count(*) from plm_collaboration_item where item_id=? and deleted_flag=0";case "mold"->"select count(*) from plm_collaboration_mold_set where mold_set_id=? and deleted_flag=0";case "product"->"select count(*) from plm_product where product_id=? and deleted_flag=0";case "file"->"select count(*) from plm_attachment where attachment_id=? and deleted_flag=0";default->throw invalid("授权类型无效");};if(jdbc.queryForObject(sql,Long.class,s.entityId())==0)throw invalid("授权对象不存在："+s.entityType()+" #"+s.entityId());}
  Set<String> allowedGroups=switch(role){case "supplier"->Set.of("engineering","logistics");case "mexico"->Set.of("mexico");case "finance"->Set.of();default->Set.of("market","engineering","logistics","mexico","production");};
  List<String> groups=input.fieldGroups()==null?switch(role){case "supplier"->List.of("engineering","logistics");case "mexico"->List.of("mexico");case "domestic"->List.of("market","engineering","logistics","production");default->List.of();}:input.fieldGroups();if(!allowedGroups.containsAll(groups))throw invalid("字段职责超出固定角色范围");
  String ding=input.dingtalkUserId()==null||input.dingtalkUserId().isBlank()?null:input.dingtalkUserId().trim();
  if(ding!=null&&jdbc.queryForObject("select count(*) from plm_pilot_account where dingtalk_user_id=? and user_id<>?",Long.class,ding,id==null?-1:id)>0)throw invalid("钉钉身份已关联其他账号");
  if(id==null){if(jdbc.queryForObject("select count(*) from sys_user where lower(username)=lower(?)",Long.class,input.username())>0)throw invalid("登录账号已存在");id=jdbc.queryForObject("insert into sys_user(user_code,username,login_name,user_name,display_name,department_name,password_hash,formal_flag,all_permissions,status,created_by,updated_by) values(?,?,?,?,?,?,?,1,?,?,?,?) returning user_id",Long.class,input.username(),input.username(),input.username(),input.displayName().trim(),input.displayName().trim(),input.departmentName().trim(),encoder.encode(input.password()),admin,status,actor.username(),actor.username());}
  else {jdbc.update("update sys_user set user_name=?,display_name=?,department_name=?,all_permissions=?,status=?,updated_at=now(),updated_by=? where user_id=?",input.displayName().trim(),input.displayName().trim(),input.departmentName().trim(),admin,status,actor.username(),id);if(input.password()!=null&&!input.password().isBlank())jdbc.update("update sys_user set password_hash=? where user_id=?",encoder.encode(input.password()),id);}
  jdbc.update("insert into plm_pilot_account(user_id,role_code,permissions,all_objects,dingtalk_user_id,created_by,updated_by) values(?,?,?::jsonb,?,?,?,?) on conflict(user_id) do update set role_code=excluded.role_code,permissions=excluded.permissions,all_objects=excluded.all_objects,dingtalk_user_id=excluded.dingtalk_user_id,version_no=plm_pilot_account.version_no+1,updated_at=now(),updated_by=excluded.updated_by",id,role,toJson(permissions),admin||input.allObjects(),ding,actor.username(),actor.username());
  jdbc.update("delete from plm_pilot_scope where user_id=?",id);for(var scope:new LinkedHashSet<>(scopes))jdbc.update("insert into plm_pilot_scope(user_id,entity_type,entity_id) values(?,?,?)",id,scope.entityType(),scope.entityId());
  jdbc.update("delete from plm_collaboration_assignment where user_id=?",id);for(String group:new LinkedHashSet<>(groups))jdbc.update("insert into plm_collaboration_assignment(user_id,field_group) values(?,?)",id,group);
  Map<String,Object> after=new LinkedHashMap<>();
  after.put("role",role);after.put("status",status);after.put("scopes",new LinkedHashSet<>(scopes));after.put("permissions",permissions);after.put("fieldGroups",new LinkedHashSet<>(groups));
  after.put("displayName",input.displayName().trim());after.put("departmentName",input.departmentName().trim());after.put("allPermissions",admin);after.put("allObjects",admin||input.allObjects());after.put("dingtalkUserId",ding);
  // Resolved before mutation, so changing this account cannot change the audit identity.
  logs.logRequired(OperationLogCreateCommand.builder().action("PILOT_USER_GRANTS_SAVE").businessType("PILOT_USER").businessId(String.valueOf(id)).businessCode(input.username()).businessName(input.displayName()).detailJson(toJson(Map.of("before",before,"after",after,"passwordChanged",input.password()!=null&&!input.password().isBlank()))).request(request).build(),actor);
  return Map.of("userId",id,"saved",true);
 }
 private List<String> readList(String raw){try{return json.readValue(raw,json.getTypeFactory().constructCollectionType(List.class,String.class));}catch(Exception e){throw invalid("权限配置无效");}}
 private String toJson(Object object){try{return json.writeValueAsString(object);}catch(Exception e){throw invalid("授权内容无效");}}
 private BusinessException invalid(String message){return new BusinessException(40001,message);}
}
