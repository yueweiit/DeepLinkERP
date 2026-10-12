package com.yuewei.plm.module.collaboration;

import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import java.time.OffsetDateTime;
import lombok.RequiredArgsConstructor;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;
import static com.yuewei.plm.module.collaboration.MoldCodeSourceTypes.*;

@RestController
@Validated
@RequiredArgsConstructor
public class MoldCodeSourceController {
    private final MoldCodeSourceService service;
    private <T> ResponseVO<T> ok(T value,HttpServletRequest request) {return ResponseVO.success(value,RequestIdUtil.getRequestId(request),OffsetDateTime.now());}
    @GetMapping("/api/v1/molds/source-codes") public ResponseVO<?> page(@Valid Query query,HttpServletRequest request) {return ok(service.page(query),request);}
    @GetMapping("/api/v1/molds/source-codes/summary") public ResponseVO<?> summary(HttpServletRequest request) {return ok(service.summary(),request);}
    @PostMapping("/api/v1/molds/source-codes/erp-previews") public ResponseVO<?> preview(@Valid @RequestBody ErpPreview dto,HttpServletRequest request) {return ok(service.previewErp(dto),request);}
    @PostMapping("/api/v1/integrations/dingtalk/mold-codes") public ResponseVO<?> receive(@Valid @RequestBody DingTalkCodeEvent dto,HttpServletRequest request) {return ok(service.receive(dto),request);}
}
