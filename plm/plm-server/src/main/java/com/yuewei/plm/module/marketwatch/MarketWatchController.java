package com.yuewei.plm.module.marketwatch;

import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.marketwatch.MarketWatchTypes.BulkUpdate;
import com.yuewei.plm.module.marketwatch.MarketWatchTypes.Promote;
import com.yuewei.plm.module.marketwatch.MarketWatchTypes.UpdateItem;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Positive;
import java.time.OffsetDateTime;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.util.MultiValueMap;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

@RestController
@Validated
@RequiredArgsConstructor
@RequestMapping("/api/v1/market-watch")
public class MarketWatchController {
    private final MarketWatchService service;

    private <T> ResponseVO<T> ok(T data,HttpServletRequest request) {
        return ResponseVO.success(data,RequestIdUtil.getRequestId(request),OffsetDateTime.now());
    }

    @GetMapping("/config") public ResponseVO<?> config(HttpServletRequest request) {return ok(service.config(),request);}
    @GetMapping("/health") public ResponseVO<?> health(HttpServletRequest request) {return ok(service.health(),request);}
    @GetMapping("/summary") public ResponseVO<?> summary(HttpServletRequest request) {return ok(service.summary(),request);}
    @GetMapping("/items") public ResponseVO<?> items(@RequestParam MultiValueMap<String,String> query,HttpServletRequest request) {return ok(service.items(query),request);}
    @GetMapping("/items/{kind}/{id}") public ResponseVO<?> detail(@PathVariable @Pattern(regexp="phone|candidate") String kind,@PathVariable @Positive long id,HttpServletRequest request) {return ok(service.detail(kind,id),request);}
    @PatchMapping("/items/{kind}/{id}") public ResponseVO<?> update(@PathVariable @Pattern(regexp="phone|candidate") String kind,@PathVariable @Positive long id,@Valid @RequestBody UpdateItem body,HttpServletRequest request) {return ok(service.update(kind,id,body),request);}
    @PostMapping("/items/bulk") public ResponseVO<?> bulk(@Valid @RequestBody BulkUpdate body,HttpServletRequest request) {return ok(service.bulk(body),request);}
    @GetMapping("/promotion-options") public ResponseVO<?> promotionOptions(@RequestParam @Pattern(regexp="phone|candidate") String kind,@RequestParam @Positive long id,HttpServletRequest request) {return ok(service.promotionOptions(kind,id),request);}
    @PostMapping("/promotions") public ResponseVO<?> promote(@Valid @RequestBody Promote body,HttpServletRequest request) {return ok(service.promote(body,request),request);}

    @GetMapping("/export.csv")
    public ResponseEntity<byte[]> export(@RequestParam MultiValueMap<String,String> query) {
        MarketWatchClient.CsvFile file=service.export(query);
        return ResponseEntity.ok()
            .header(HttpHeaders.CONTENT_DISPOSITION,ContentDisposition.attachment().filename(file.filename()).build().toString())
            .contentType(MediaType.parseMediaType("text/csv;charset=UTF-8"))
            .body(file.bytes());
    }
}
