package com.yuewei.plm.module.collaboration;

import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.pilot.PilotAccessService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.time.OffsetDateTime;
import lombok.RequiredArgsConstructor;
import org.springframework.http.*;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

@RestController @RequiredArgsConstructor @Validated
@RequestMapping("/api/v1/collaboration-plans/schedules")
public class MoldScheduleController {
    private final MoldScheduleService service;
    private final CollaborationImportService imports;
    private final PilotAccessService access;
    private ResponseVO<?> ok(Object data,HttpServletRequest request) {return ResponseVO.success(data,RequestIdUtil.getRequestId(request),OffsetDateTime.now());}
    @GetMapping public ResponseVO<?> page(@Valid MoldScheduleTypes.Query query,HttpServletRequest request) {return ok(service.page(query),request);}
    @GetMapping("/options") public ResponseVO<?> options(HttpServletRequest request) {return ok(service.options(),request);}
    @GetMapping("/{id}") public ResponseVO<?> detail(@PathVariable @Positive long id,HttpServletRequest request) {return ok(service.detail(id),request);}
    @PostMapping("/batch-save") public ResponseVO<?> save(@Valid @RequestBody CollaborationTypes.BatchSave dto,HttpServletRequest request) {return ok(service.save(dto,request),request);}
    @PostMapping("/{id}/plans") public ResponseVO<?> plan(@PathVariable @Positive long id,@Valid @RequestBody MoldScheduleTypes.ConfirmPlan dto,HttpServletRequest request) {return ok(service.confirmPlan(id,dto),request);}
    @GetMapping("/{id}/history") public ResponseVO<?> history(@PathVariable @Positive long id,@RequestParam(defaultValue="1") @Min(1) int page,@RequestParam(defaultValue="20") @Min(1) @Max(100) int size,HttpServletRequest request) {return ok(service.history(id,page,size),request);}
    @GetMapping("/tasks") public ResponseVO<?> tasks(@Valid MoldScheduleTypes.Query query,HttpServletRequest request) {return ok(service.tasks(query),request);}
    @PostMapping("/reminders/enqueue") public ResponseVO<?> reminders(HttpServletRequest request) {return ok(service.enqueueReminders(),request);}
    @PostMapping("/imports/preview") public ResponseVO<?> preview(@RequestParam("file") MultipartFile file,HttpServletRequest request) {access.requireDomesticView();access.requirePermission("schedule:write");return ok(imports.preview("schedule",file,access.visibleSqlClause("item","i.item_id"),access.visibleSqlClause("mold","s.mold_set_id")),request);}
    @PostMapping("/imports/{token}/commit") public ResponseVO<?> commit(@PathVariable String token,@Valid @RequestBody CollaborationTypes.ImportCommit dto,HttpServletRequest request) {access.requireDomesticView();access.requirePermission("schedule:write");for(var row:dto.rows()) if(!row.skip()) {if(row.itemId()!=null) access.requireItem(row.itemId());if(row.moldSetId()!=null) access.requireMold(row.moldSetId());}return ok(imports.commit(token,dto,request,"schedule"),request);}
    @GetMapping("/template") public ResponseEntity<byte[]> template(@RequestParam(defaultValue="true") boolean blank,@Valid CollaborationTypes.Query query) {access.requireDomesticView();access.requirePermission("schedule:read");query.setSchedule(true);return ResponseEntity.ok().header(HttpHeaders.CONTENT_DISPOSITION,"attachment; filename=mold-schedule.xlsx").contentType(MediaType.parseMediaType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")).body(imports.template("schedule",query,blank,access.visibleSqlClause("mold","s.mold_set_id")));}
}
