package com.yuewei.plm.module.pilot;
import com.yuewei.plm.common.exception.BusinessException;import com.yuewei.plm.common.security.CurrentUserContext;
import jakarta.servlet.http.*;import java.util.*;import java.util.regex.Pattern;import lombok.RequiredArgsConstructor;import org.springframework.stereotype.Component;import org.springframework.web.servlet.HandlerInterceptor;

/** Central table-driven compatibility boundary. Restricted pilot users fail closed. */
@Component @RequiredArgsConstructor
public class PilotSecurityInterceptor implements HandlerInterceptor {
 private final PilotAccessService access;
 private record ObjectRule(Pattern path,String type,String permission){}
 private static final List<ObjectRule> OBJECTS=List.of(
  new ObjectRule(Pattern.compile("/api/v1/attachments/(\\d+)(?:/.*)?"),"file","file:read"),
  new ObjectRule(Pattern.compile("/api/v1/molds/(\\d+)(?:/.*)?"),"mold","collaboration:view"),
  new ObjectRule(Pattern.compile("/api/v1/collaboration-plans/items/(\\d+)(?:/.*)?"),"item","collaboration:view"),
  new ObjectRule(Pattern.compile("/api/v1/boms/(\\d+)(?:/.*)?"),"bom","product:view"),
  new ObjectRule(Pattern.compile("/api/v1/(?:products|projects)/(\\d+)(?:/.*)?"),"product","project:view"));
 private static final Map<String,String> COLLECTIONS=Map.ofEntries(
  Map.entry("/api/v1/dashboard","dashboard:view"),Map.entry("/api/v1/projects","project:view"),Map.entry("/api/v1/products","product:view"),
  Map.entry("/api/v1/bom","product:view"),Map.entry("/api/v1/process","process:view"),Map.entry("/api/v1/inventories","inventory:view"),
  Map.entry("/api/v1/suppliers","supplier:view"),Map.entry("/api/v1/orders","order:view"),Map.entry("/api/v1/production-orders","production-order:view"),
  Map.entry("/api/v1/collaboration-plans","collaboration:view"),Map.entry("/api/v1/molds","collaboration:view"),Map.entry("/api/v1/code-items","product:view"),
  Map.entry("/api/v1/file-center","file:read"),Map.entry("/api/v1/reports","report:view"));
 private static final List<String> SAFE=List.of("/api/v1/auth/profile","/api/v1/auth/logout","/api/v1/pilot/me");
 @Override public boolean preHandle(HttpServletRequest r,HttpServletResponse response,Object handler){
  if(CurrentUserContext.get().isEmpty())return true;
  var a=access.access();CurrentUserContext.set(a.actor());if(a.actor().allPermissions())return true;
  String path=r.getRequestURI();boolean read=Set.of("GET","HEAD").contains(r.getMethod());
  if(path.contains("cost-summary")||path.contains("cost-items")||path.contains("/costs/")||path.endsWith("/costs")||path.startsWith("/api/v1/cost"))access.requirePermission(financeAction(path,read));
  if(!a.pilot())return true; // Historical non-financial workflows retain their behavior.
  if(SAFE.contains(path))return true;
  if(path.startsWith("/api/v1/pilot/tasks")){access.requirePermission("pilot:tasks");return true;}
  if(path.startsWith("/api/v1/pilot/")||path.startsWith("/api/v1/system/")){access.requireAdministrator();return true;}
  if(access.isExternal()){
   for(var rule:OBJECTS){var m=rule.path().matcher(path);if(m.matches()&&rule.type().equals("file")&&read){access.requireFile(Long.parseLong(m.group(1)));return true;}}
   throw denied();
  }
  if(path.startsWith("/api/v1/pilot-delivery/")){
   if(path.startsWith("/api/v1/pilot-delivery/tasks")||!read){access.requireAdministrator();return true;}
   access.requirePermission(path.contains("export")?"finance:export":"report:view");return true;
  }
  if(path.startsWith("/api/v1/development")){access.requirePermission(financeAction(path,read));return true;}
  if(path.startsWith("/api/v1/collaboration-plans/schedules")){access.requirePermission(path.endsWith("/remind")?"schedule:remind":read?"schedule:read":"schedule:write");return true;}
  if(path.matches(".*(?:export|templates|download-xlsx).*"))access.requireFinanceExport();
  for(var rule:OBJECTS){var m=rule.path().matcher(path);if(m.matches()){
   access.requirePermission(rule.permission());long id=Long.parseLong(m.group(1));switch(rule.type()){case "file"->access.requireFile(id);case "mold"->access.requireMold(id);case "item"->access.requireItem(id);case "product"->access.requireProduct(id);case "bom"->access.requireBom(id);default->throw denied();}
   if(rule.type().equals("file")&&!read)access.requirePermission(path.endsWith("/release")?"documents:publish":"documents:write");
   if(path.contains("/boms")&&!read)access.requirePermission(path.endsWith("/publish")?"bom:publish":"bom:write");
   if(!read&&!a.role().equals("domestic")&&!path.contains("cost-items"))throw denied();return true;}}
  // Old collection endpoints cannot apply object scopes; only explicitly unrestricted domestic users may use them.
  if(a.allObjects()&&a.role().equals("domestic"))for(var entry:COLLECTIONS.entrySet())if(path.startsWith(entry.getKey())){access.requirePermission(entry.getValue());if(path.startsWith("/api/v1/boms")&&!read)access.requirePermission(path.endsWith("/publish")?"bom:publish":"bom:write");return true;}
  throw denied();
 }
 private static String financeAction(String path,boolean read){return path.contains("export")?"finance:export":path.endsWith("/confirm")?"finance:confirm":read?"finance:read":"finance:write";}
 private static BusinessException denied(){return new BusinessException(40103,"试点账号无权使用该入口，请使用已分配的任务或授权视图");}
}
