package com.yuewei.plm.module.pilot;
import com.yuewei.plm.common.vo.ResponseVO;import com.yuewei.plm.common.util.RequestIdUtil;import jakarta.servlet.http.HttpServletRequest;import jakarta.validation.Valid;import jakarta.validation.constraints.*;import java.time.OffsetDateTime;import lombok.RequiredArgsConstructor;import org.springframework.web.bind.annotation.*;
@RestController @RequiredArgsConstructor @RequestMapping("/api/v1/pilot/dingtalk")
public class PilotDingTalkSsoController {
 private final PilotDingTalkSsoService service;public record Code(@NotBlank @Size(max=1024) String code){}
 private final java.util.Map<String,long[]> attempts=new java.util.HashMap<>();
 @GetMapping("/status")public ResponseVO<?> status(HttpServletRequest r){return ResponseVO.success(service.status(),RequestIdUtil.getRequestId(r),OffsetDateTime.now());}
 @PostMapping("/login")public ResponseVO<?> login(@Valid @RequestBody Code code,HttpServletRequest r){limit(r.getRemoteAddr());return ResponseVO.success(service.login(code.code()),RequestIdUtil.getRequestId(r),OffsetDateTime.now());}
 private synchronized void limit(String address){long now=System.currentTimeMillis();attempts.entrySet().removeIf(e->now-e.getValue()[0]>60000);if(attempts.size()>1000)throw new com.yuewei.plm.common.exception.BusinessException(50301,"免登服务繁忙，请稍后重试");long[] window=attempts.computeIfAbsent(address,k->new long[]{now,0});if(++window[1]>10)throw new com.yuewei.plm.common.exception.BusinessException(40103,"免登请求过于频繁，请稍后重试");}
}
