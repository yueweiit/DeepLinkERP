package com.yuewei.plm.module.attachment.controller;
import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.attachment.service.AttachmentVersionService;
import jakarta.servlet.http.HttpServletRequest;
import java.time.OffsetDateTime;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
@RestController @RequiredArgsConstructor @RequestMapping("/api/v1/attachments/{id}")
public class AttachmentVersionController {
    private final AttachmentVersionService service;
    private ResponseVO<?> ok(Object value,HttpServletRequest r){return ResponseVO.success(value,RequestIdUtil.getRequestId(r),OffsetDateTime.now());}
    @GetMapping("/versions") public ResponseVO<?> versions(@PathVariable long id,HttpServletRequest r){return ok(service.versions(id),r);}
    @PostMapping("/versions") public ResponseVO<?> upload(@PathVariable long id,@RequestParam MultipartFile file,@RequestParam String versionNo,@RequestParam String reason,HttpServletRequest r){return ok(service.upload(id,file,versionNo,reason,r),r);}
    @PostMapping("/release") public ResponseVO<?> release(@PathVariable long id,@RequestBody AttachmentVersionService.Publication dto,HttpServletRequest r){return ok(service.publish(id,dto,r),r);}
}
