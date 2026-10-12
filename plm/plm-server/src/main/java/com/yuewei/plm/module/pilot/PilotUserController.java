package com.yuewei.plm.module.pilot;
import com.yuewei.plm.common.vo.ResponseVO;import com.yuewei.plm.common.util.RequestIdUtil;
import jakarta.servlet.http.HttpServletRequest;import jakarta.validation.Valid;import jakarta.validation.constraints.*;import java.time.OffsetDateTime;import lombok.RequiredArgsConstructor;import org.springframework.validation.annotation.Validated;import org.springframework.web.bind.annotation.*;
@RestController @RequiredArgsConstructor @Validated @RequestMapping("/api/v1/pilot")
public class PilotUserController {
 private final PilotUserService users;private final PilotAccessService access;
 private <T>ResponseVO<T> ok(T data,HttpServletRequest r){return ResponseVO.success(data,RequestIdUtil.getRequestId(r),OffsetDateTime.now());}
 @GetMapping("/me") public ResponseVO<?> me(HttpServletRequest r){return ok(access.userView(access.actor()),r);}
 @GetMapping("/users") public ResponseVO<?> users(HttpServletRequest r){return ok(users.users(),r);}
 @GetMapping("/roles") public ResponseVO<?> roles(HttpServletRequest r){return ok(users.roles(),r);}
 @GetMapping("/scope-options") public ResponseVO<?> options(@RequestParam String type,@RequestParam(defaultValue="") @Size(max=128) String keyword,HttpServletRequest r){return ok(users.scopeOptions(type,keyword),r);}
 @PostMapping("/users") public ResponseVO<?> create(@Valid @RequestBody PilotUserService.UserInput input,HttpServletRequest r){return ok(users.save(null,input,r),r);}
 @PutMapping("/users/{id}") public ResponseVO<?> update(@PathVariable @Positive long id,@Valid @RequestBody PilotUserService.UserInput input,HttpServletRequest r){return ok(users.save(id,input,r),r);}
}
