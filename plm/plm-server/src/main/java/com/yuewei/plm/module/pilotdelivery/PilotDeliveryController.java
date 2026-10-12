package com.yuewei.plm.module.pilotdelivery;
import com.yuewei.plm.common.vo.ResponseVO;import com.yuewei.plm.common.util.RequestIdUtil;
import jakarta.servlet.http.HttpServletRequest;import java.time.OffsetDateTime;import lombok.RequiredArgsConstructor;import org.springframework.web.bind.annotation.*;import org.springframework.http.*;
@RestController @RequiredArgsConstructor @RequestMapping("/api/v1/pilot-delivery")
public class PilotDeliveryController {
 private final PilotTrialService trials;private final PilotDeliveryQueue queue;private final PilotExportService exports;
 private ResponseVO<?> ok(Object data,HttpServletRequest r){return ResponseVO.success(data,RequestIdUtil.getRequestId(r),OffsetDateTime.now());}
 @GetMapping("/trials") public ResponseVO<?> list(HttpServletRequest r){return ok(trials.list(),r);}
 @GetMapping("/options") public ResponseVO<?> options(HttpServletRequest r){return ok(trials.options(),r);}
 @GetMapping("/trials/{id}") public ResponseVO<?> detail(@PathVariable long id,HttpServletRequest r){return ok(trials.detail(id),r);}
 @PostMapping("/trials") public ResponseVO<?> create(@RequestBody PilotTrialService.Save dto,HttpServletRequest r){return ok(trials.save(null,dto),r);}
 @PutMapping("/trials/{id}") public ResponseVO<?> update(@PathVariable long id,@RequestBody PilotTrialService.Save dto,HttpServletRequest r){return ok(trials.save(id,dto),r);}
 @PostMapping("/trials/{id}/start") public ResponseVO<?> start(@PathVariable long id,@RequestBody PilotTrialService.Start dto,HttpServletRequest r){return ok(trials.start(id,dto),r);}
 @PostMapping("/trials/{id}/review") public ResponseVO<?> review(@PathVariable long id,@RequestBody PilotTrialService.Review dto,HttpServletRequest r){return ok(trials.review(id,dto),r);}
 @GetMapping("/trials/{id}/metrics") public ResponseVO<?> metrics(@PathVariable long id,HttpServletRequest r){return ok(trials.metrics(id),r);}
 @GetMapping("/trials/{id}/export") public ResponseEntity<byte[]> export(@PathVariable long id,HttpServletRequest r){return ResponseEntity.ok().header(HttpHeaders.CONTENT_DISPOSITION,"attachment; filename=plm-pilot-"+id+".zip").contentType(MediaType.parseMediaType("application/zip")).body(exports.export(id,r));}
 @GetMapping("/configuration") public ResponseVO<?> config(HttpServletRequest r){return ok(queue.configuration(),r);}
 @GetMapping("/tasks") public ResponseVO<?> tasks(@RequestParam(defaultValue="1")int page,@RequestParam(defaultValue="50")int size,@RequestParam(required=false)String status,HttpServletRequest r){return ok(queue.page(page,size,status),r);}
 @PostMapping("/tasks/{id}/retry") public ResponseVO<?> retry(@PathVariable long id,HttpServletRequest r){queue.retry(id);return ok(null,r);}
}
