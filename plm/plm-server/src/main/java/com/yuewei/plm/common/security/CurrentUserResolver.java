package com.yuewei.plm.common.security;

import com.yuewei.plm.common.exception.BusinessException;
import java.util.Objects;
import org.springframework.jdbc.core.JdbcTemplate;

/** Shared real-account resolution for collaboration and pilot authorization. */
public final class CurrentUserResolver {
 private CurrentUserResolver() {}
 public static CurrentUser resolve(JdbcTemplate jdbc) {
  return resolve(jdbc,CurrentUserContext.get().orElseThrow(()->new BusinessException(40101,"请先登录")));
 }
 public static CurrentUser resolve(JdbcTemplate jdbc,CurrentUser claimed) {
  var users=jdbc.queryForList("select user_id,username,display_name,all_permissions from sys_user where user_id=? and deleted_flag=0 and status='active'",claimed.userId());
  if(users.isEmpty()) throw new BusinessException(40101,"账号已停用或失效");
  var user=users.get(0);
  return new CurrentUser(((Number)user.get("user_id")).longValue(),Objects.toString(user.get("username")),Objects.toString(user.get("display_name")),Boolean.TRUE.equals(user.get("all_permissions")));
 }
}
