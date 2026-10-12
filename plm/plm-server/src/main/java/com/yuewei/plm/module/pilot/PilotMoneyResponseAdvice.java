package com.yuewei.plm.module.pilot;
import com.fasterxml.jackson.databind.*;import com.fasterxml.jackson.databind.node.ObjectNode;import com.yuewei.plm.common.security.CurrentUserContext;
import java.util.*;import lombok.RequiredArgsConstructor;import org.springframework.core.MethodParameter;import org.springframework.http.*;import org.springframework.http.converter.*;import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;import org.springframework.http.server.*;import org.springframework.web.bind.annotation.RestControllerAdvice;import org.springframework.web.servlet.mvc.method.annotation.ResponseBodyAdvice;

/** Defense in depth for legacy nested DTOs; authoritative new financial routes still reject access. */
@RestControllerAdvice @RequiredArgsConstructor
public class PilotMoneyResponseAdvice implements ResponseBodyAdvice<Object> {
 private final PilotAccessService access;private final ObjectMapper json;
 @Override public boolean supports(MethodParameter p,Class<? extends HttpMessageConverter<?>> type){return MappingJackson2HttpMessageConverter.class.isAssignableFrom(type);}
 @Override public Object beforeBodyWrite(Object body,MethodParameter p,MediaType type,Class<? extends HttpMessageConverter<?>> converter,ServerHttpRequest request,ServerHttpResponse response){
  if(body==null||CurrentUserContext.get().isEmpty())return body;
  try{if(access.hasPermission("finance:read"))return body;}catch(com.yuewei.plm.common.exception.BusinessException ignored){/* Preserve the handler's expired-account error without a second authorization failure. */}
  JsonNode result=json.valueToTree(body);redact(result);return result;
 }
 static void redact(JsonNode node){if(node.isObject()){ObjectNode object=(ObjectNode)node;List<String> remove=new ArrayList<>();object.fields().forEachRemaining(f->{if(PilotMoneyFields.isProtected(f.getKey()))remove.add(f.getKey());else redact(f.getValue());});remove.forEach(object::remove);}else if(node.isArray())node.forEach(PilotMoneyResponseAdvice::redact);}
}
