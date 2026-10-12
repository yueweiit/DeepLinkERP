package com.yuewei.plm.module.pilot;
import com.fasterxml.jackson.databind.ObjectMapper;import com.yuewei.plm.common.exception.BusinessException;import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.module.auth.service.TokenSessionService;import com.yuewei.plm.module.auth.vo.LoginVO;
import com.yuewei.plm.infrastructure.http.SafeHttpTransport;
import java.net.*;import java.net.http.*;import java.time.Duration;import java.util.*;
import org.springframework.beans.factory.annotation.Value;import org.springframework.jdbc.core.JdbcTemplate;import org.springframework.stereotype.Service;

/** Enterprise micro-app authCode exchange. No mapping means no account or session. */
@Service
public class PilotDingTalkSsoService {
 private final JdbcTemplate jdbc;private final ObjectMapper json;private final TokenSessionService tokens;private final PilotAccessService access;
 private final HttpClient http=SafeHttpTransport.client();
 @org.springframework.beans.factory.annotation.Autowired private com.yuewei.plm.module.operationlog.service.OperationLogService logs;
 @Value("${app.pilot.dingtalk-sso.enabled:${PLM_PILOT_DINGTALK_SSO_ENABLED:false}}") private boolean enabled;
 @Value("${app.pilot.dingtalk-sso.corp-id:${PLM_PILOT_DINGTALK_CORP_ID:}}") private String corpId;
 @Value("${app.pilot.dingtalk-sso.app-key:${PLM_PILOT_DINGTALK_APP_KEY:}}") private String appKey;
 @Value("${app.pilot.dingtalk-sso.app-secret:${PLM_PILOT_DINGTALK_APP_SECRET:}}") private String appSecret;
 public PilotDingTalkSsoService(JdbcTemplate jdbc,ObjectMapper json,TokenSessionService tokens,PilotAccessService access){this.jdbc=jdbc;this.json=json;this.tokens=tokens;this.access=access;}
 public Map<String,Object> status(){boolean ready=enabled&&!appKey.isBlank()&&!appSecret.isBlank()&&!corpId.isBlank();return Map.of("enabled",ready,"corpId",ready?corpId:"","mode","enterprise_micro_app","message",ready?"需在钉钉真实应用内完成免登联调":"未启用钉钉免登，使用现有网页登录；未映射账号不会自动创建");}
 public LoginVO login(String code){
  if(!Boolean.TRUE.equals(status().get("enabled")))throw new BusinessException(50301,"钉钉免登尚未配置，请使用网页登录");
  if(code==null||code.isBlank()||code.length()>1024)throw new BusinessException(40001,"免登码无效");
  try{
   var token=post("https://api.dingtalk.com/v1.0/oauth2/accessToken",Map.of("appKey",appKey,"appSecret",appSecret));
   String appToken=token.path("accessToken").asText();if(appToken.isBlank())throw new BusinessException(50301,"钉钉凭证交换失败");
   var info=post("https://oapi.dingtalk.com/topapi/v2/user/getuserinfo?access_token="+URLEncoder.encode(appToken,java.nio.charset.StandardCharsets.UTF_8),Map.of("code",code));
   if(info.path("errcode").asInt(-1)!=0)throw new BusinessException(40101,"钉钉免登码无效或已过期");
   String uid=info.path("result").path("userid").asText();if(uid.isBlank())throw new BusinessException(40101,"未获得真实钉钉身份");
   return mappedSession(uid);
  }catch(BusinessException e){throw e;}catch(Exception e){if(e instanceof InterruptedException)Thread.currentThread().interrupt();throw new BusinessException(50301,"钉钉免登服务暂不可用");}
 }
 LoginVO mappedSession(String dingtalkUserId){
  var rows=jdbc.queryForList("select u.user_id,u.username,u.display_name,u.all_permissions from plm_pilot_account p join sys_user u on u.user_id=p.user_id where p.dingtalk_user_id=? and u.status='active' and u.deleted_flag=0",dingtalkUserId);
  if(rows.size()!=1)throw new BusinessException(40103,"该钉钉身份未关联有效PLM账号，请联系管理员");
  var r=rows.get(0);var actor=new CurrentUser(((Number)r.get("user_id")).longValue(),r.get("username").toString(),r.get("display_name").toString(),Boolean.TRUE.equals(r.get("all_permissions")));
  var user=access.userView(actor);String session=tokens.createSession(actor);
  if(logs!=null){var previous=com.yuewei.plm.common.security.CurrentUserContext.get();com.yuewei.plm.common.security.CurrentUserContext.set(actor);try{logs.logSuccess(com.yuewei.plm.module.operationlog.service.OperationLogCreateCommand.builder().action("AUTH_DINGTALK_LOGIN").businessType("AUTH").businessId(String.valueOf(actor.userId())).businessCode(actor.username()).businessName(actor.displayName()).build());}finally{if(previous.isPresent())com.yuewei.plm.common.security.CurrentUserContext.set(previous.get());else com.yuewei.plm.common.security.CurrentUserContext.clear();}}
  return LoginVO.builder().token(session).tokenType("Bearer").expiresInSeconds(tokens.getExpiresInSeconds()).user(user).build();
 }
 private com.fasterxml.jackson.databind.JsonNode post(String url,Object payload)throws Exception{
  var response=http.send(HttpRequest.newBuilder(URI.create(url)).timeout(Duration.ofSeconds(8)).header("Content-Type","application/json").POST(HttpRequest.BodyPublishers.ofString(json.writeValueAsString(payload))).build(),SafeHttpTransport.boundedBody(65536));
  if(response.statusCode()!=200)throw new BusinessException(50301,"钉钉免登服务返回异常");return json.readTree(response.body());
 }
}
