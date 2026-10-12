package com.yuewei.plm.module.pilot;
import com.yuewei.plm.common.vo.ResponseVO;import com.yuewei.plm.common.util.RequestIdUtil;import com.yuewei.plm.module.collaboration.CollaborationTypes.RowPatch;
import jakarta.servlet.http.HttpServletRequest;import jakarta.validation.Valid;import jakarta.validation.constraints.*;import java.time.OffsetDateTime;import lombok.RequiredArgsConstructor;import org.springframework.validation.annotation.Validated;import org.springframework.web.bind.annotation.*;
@RestController @Validated @RequiredArgsConstructor @RequestMapping("/api/v1/pilot/tasks")
public class PilotMobileTaskController {
 private final PilotMobileTaskService service;private <T>ResponseVO<T> ok(T data,HttpServletRequest r){return ResponseVO.success(data,RequestIdUtil.getRequestId(r),OffsetDateTime.now());}
 @GetMapping public ResponseVO<?> page(@RequestParam(defaultValue="1") @Min(1) int page,@RequestParam(defaultValue="20") @Min(1) @Max(50) int size,@RequestParam(defaultValue="") @Size(max=128) String keyword,HttpServletRequest r){return ok(service.page(page,size,keyword),r);}
 @PostMapping("/{id}/{action}") public ResponseVO<?> save(@PathVariable @Positive long id,@PathVariable String action,@Valid @RequestBody RowPatch patch,HttpServletRequest r){return ok(service.save(id,action,patch,r),r);}
 @GetMapping("/{id}/files") public ResponseVO<?> files(@PathVariable @Positive long id,HttpServletRequest r){return ok(service.files(id),r);}
}
