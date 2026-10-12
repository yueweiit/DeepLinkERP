package com.yuewei.plm.module.collaboration;

import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.common.util.RequestIdUtil;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.time.OffsetDateTime;
import lombok.RequiredArgsConstructor;
import org.springframework.http.*;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import static com.yuewei.plm.module.collaboration.CollaborationTypes.*;

@RestController
@Validated
@RequiredArgsConstructor
@RequestMapping("/api/v1/collaboration-plans")
public class CollaborationController {
    private final CollaborationService service;
    private final CollaborationImportService imports;
    private <T> ResponseVO<T> ok(T data,HttpServletRequest request) {return ResponseVO.success(data,RequestIdUtil.getRequestId(request),OffsetDateTime.now());}
    @GetMapping public ResponseVO<?> page(@Valid Query query,HttpServletRequest request) {return ok(service.page(query),request);}
    @GetMapping("/options") public ResponseVO<?> options(HttpServletRequest request) {return ok(service.options(),request);}
    @GetMapping("/items/{id}") public ResponseVO<?> item(@PathVariable @Positive long id,HttpServletRequest request) {return ok(service.item(id),request);}
    @PostMapping("/items") public ResponseVO<?> create(@Valid @RequestBody CreateItem dto,HttpServletRequest request) {return ok(service.createItem(dto,request),request);}
    @PostMapping("/items/{id}/mold-sets") public ResponseVO<?> createSet(@PathVariable @Positive long id,@Valid @RequestBody CreateMoldSet dto,HttpServletRequest request) {return ok(service.createMoldSet(id,dto,request),request);}
    @PutMapping("/items/{id}/projects") public ResponseVO<?> link(@PathVariable @Positive long id,@Valid @RequestBody LinkProjects dto,HttpServletRequest request) {return ok(service.linkProjects(id,dto,request),request);}
    @PostMapping("/batch-save") public ResponseVO<?> save(@Valid @RequestBody BatchSave dto,HttpServletRequest request) {return ok(service.save(dto,request),request);}
    @GetMapping("/items/{id}/history") public ResponseVO<?> history(@PathVariable @Positive long id,@RequestParam(defaultValue="1") @Min(1) int page,@RequestParam(defaultValue="20") @Min(1) @Max(100) int size,HttpServletRequest request) {return ok(service.history(id,page,size),request);}
    @GetMapping("/items/{id}/references") public ResponseVO<?> references(@PathVariable @Positive long id,HttpServletRequest request) {return ok(service.references(id),request);}
    @GetMapping("/project-options") public ResponseVO<?> projects(@RequestParam(required=false) Long productLineId,@RequestParam(required=false) @Size(max=128) String keyword,HttpServletRequest request) {return ok(service.projectOptions(productLineId,keyword),request);}
    @GetMapping("/mold-code-options") public ResponseVO<?> molds(@RequestParam(required=false) Long itemId,@RequestParam(required=false) @Size(max=128) String keyword,HttpServletRequest request) {return ok(service.moldCodes(itemId,keyword),request);}
    @GetMapping("/assignments") public ResponseVO<?> assignments(HttpServletRequest request) {return ok(service.assignments(),request);}
    @GetMapping("/accounts") public ResponseVO<?> accounts(HttpServletRequest request) {return ok(service.accounts(),request);}
    @PostMapping("/brands/initialise") public ResponseVO<?> brands(HttpServletRequest request) {return ok(service.initialiseExplicitBrands(request),request);}
    @PutMapping("/assignments") public ResponseVO<?> assignments(@Valid @RequestBody Assignments dto,HttpServletRequest request) {return ok(service.saveAssignments(dto,request),request);}
    @PostMapping("/imports/{kind}/preview") public ResponseVO<?> preview(@PathVariable String kind,@RequestParam("file") MultipartFile file,HttpServletRequest request) {return ok(imports.preview(kind,file),request);}
    @PostMapping("/imports/{token}/commit") public ResponseVO<?> commit(@PathVariable String token,@Valid @RequestBody ImportCommit dto,HttpServletRequest request) {return ok(imports.commit(token,dto,request),request);}
    @GetMapping("/templates/{kind}") public ResponseEntity<byte[]> template(@PathVariable String kind,@Valid Query query,@RequestParam(defaultValue="true") boolean blank) {
        return ResponseEntity.ok().header(HttpHeaders.CONTENT_DISPOSITION,ContentDisposition.attachment().filename("collaboration-"+kind+".xlsx").build().toString())
            .contentType(MediaType.parseMediaType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")).body(imports.template(kind,query,blank));
    }
}
