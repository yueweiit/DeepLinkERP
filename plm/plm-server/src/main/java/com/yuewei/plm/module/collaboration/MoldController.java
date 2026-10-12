package com.yuewei.plm.module.collaboration;

import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.common.util.RequestIdUtil;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.time.OffsetDateTime;
import lombok.RequiredArgsConstructor;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;
import static com.yuewei.plm.module.collaboration.CollaborationTypes.*;

@RestController
@Validated
@RequiredArgsConstructor
@RequestMapping("/api/v1/molds")
public class MoldController {
    private final CollaborationService service;
    private <T> ResponseVO<T> ok(T data,HttpServletRequest request) {return ResponseVO.success(data,RequestIdUtil.getRequestId(request),OffsetDateTime.now());}
    @GetMapping public ResponseVO<?> page(@Valid Query query,HttpServletRequest request) {return ok(service.moldPage(query),request);}
    @GetMapping("/options") public ResponseVO<?> options(HttpServletRequest request) {return ok(service.moldOptions(),request);}
    @GetMapping("/{id}") public ResponseVO<?> detail(@PathVariable @Positive long id,HttpServletRequest request) {return ok(service.mold(id),request);}
    @PostMapping public ResponseVO<?> create(@Valid @RequestBody CreateMold dto,HttpServletRequest request) {return ok(service.createMoldSet(dto.itemId(),new CreateMoldSet(dto.setName(),null,null),request),request);}
    @PostMapping("/{id}/copies") public ResponseVO<?> copy(@PathVariable @Positive long id,@Valid @RequestBody CreateMoldSet dto,HttpServletRequest request) {return ok(service.copyMold(id,dto,request),request);}
    @PostMapping("/batch-save") public ResponseVO<?> save(@Valid @RequestBody BatchSave dto,HttpServletRequest request) {
        if(dto.rows().stream().anyMatch(r->!r.entityType().equals("mold_set"))) throw CollaborationFields.invalid("模具台账只保存模具套及部件字段");
        return ok(service.save(dto,request),request);
    }
    @GetMapping("/{id}/history") public ResponseVO<?> history(@PathVariable @Positive long id,@RequestParam(defaultValue="1") @Min(1) int page,@RequestParam(defaultValue="20") @Min(1) @Max(100) int size,HttpServletRequest request) {return ok(service.moldHistory(id,page,size),request);}
    @GetMapping("/{id}/references") public ResponseVO<?> references(@PathVariable @Positive long id,HttpServletRequest request) {return ok(service.moldReferences(id),request);}
    @GetMapping("/inventory-options") public ResponseVO<?> inventories(@RequestParam @Size(min=2,max=128) String keyword,HttpServletRequest request) {return ok(service.inventoryOptions(keyword),request);}
}
