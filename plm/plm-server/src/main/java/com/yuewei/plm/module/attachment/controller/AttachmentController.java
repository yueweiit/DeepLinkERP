package com.yuewei.plm.module.attachment.controller;

import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.attachment.service.AttachmentDownloadResource;
import com.yuewei.plm.module.attachment.service.AttachmentService;
import com.yuewei.plm.module.attachment.vo.AttachmentVO;
import com.yuewei.plm.module.attachment.vo.AttachmentPreviewVO;
import jakarta.servlet.http.HttpServletRequest;
import java.nio.charset.StandardCharsets;
import java.time.OffsetDateTime;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.core.io.Resource;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequiredArgsConstructor
@RequestMapping("/api/v1")
public class AttachmentController {

    private final AttachmentService attachmentService;


    @PostMapping("/products/{productId}/attachments")
    public ResponseVO<AttachmentVO> uploadProductAttachment(@PathVariable Long productId,
                                                            @RequestParam("file") MultipartFile file,
                                                            @RequestParam String fileCategory,
                                                            @RequestParam(required = false) String versionNo,
                                                            @RequestParam(required = false) String remark,
                                                            HttpServletRequest request) {
        return ResponseVO.success(
            attachmentService.uploadProductAttachment(productId, file, fileCategory, versionNo, remark, request),
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }

    @GetMapping("/products/{productId}/attachments")
    public ResponseVO<List<AttachmentVO>> listProductAttachments(@PathVariable Long productId,
                                                                 @RequestParam(required = false) String fileCategory,
                                                                 HttpServletRequest request) {
        return ResponseVO.success(
            attachmentService.listProductAttachments(productId, fileCategory),
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }
    @GetMapping("/attachments/{attachmentId}")
    public ResponseVO<AttachmentVO> detail(@PathVariable Long attachmentId, HttpServletRequest request) {
        return ResponseVO.success(attachmentService.getById(attachmentId), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @GetMapping("/attachments/{attachmentId}/preview/metadata")
    public ResponseVO<AttachmentPreviewVO> previewMetadata(@PathVariable Long attachmentId, HttpServletRequest request) {
        return ResponseVO.success(
            attachmentService.previewMetadata(attachmentId),
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }

    @GetMapping("/attachments/{attachmentId}/preview")
    public ResponseEntity<Resource> preview(@PathVariable Long attachmentId, HttpServletRequest request) {
        AttachmentDownloadResource preview = attachmentService.preview(attachmentId, request);
        MediaType contentType = MediaType.APPLICATION_OCTET_STREAM;
        if (preview.contentType() != null) {
            try {
                contentType = MediaType.parseMediaType(preview.contentType());
            } catch (Exception ignored) {
                contentType = MediaType.APPLICATION_OCTET_STREAM;
            }
        }
        return ResponseEntity.ok()
            .header(HttpHeaders.CONTENT_DISPOSITION, ContentDisposition.inline()
                .filename(preview.fileName(), StandardCharsets.UTF_8)
                .build()
                .toString())
            .contentType(contentType)
            .body(preview.resource());
    }

    @GetMapping("/attachments/{attachmentId}/download")
    public ResponseEntity<Resource> download(@PathVariable Long attachmentId, HttpServletRequest request) {
        AttachmentDownloadResource download = attachmentService.download(attachmentId, request);
        MediaType contentType = MediaType.APPLICATION_OCTET_STREAM;
        if (download.contentType() != null) {
            try {
                contentType = MediaType.parseMediaType(download.contentType());
            } catch (Exception ignored) {
                contentType = MediaType.APPLICATION_OCTET_STREAM;
            }
        }
        return ResponseEntity.ok()
            .header(HttpHeaders.CONTENT_DISPOSITION, ContentDisposition.attachment()
                .filename(download.fileName(), StandardCharsets.UTF_8)
                .build()
                .toString())
            .contentType(contentType)
            .body(download.resource());
    }

    @DeleteMapping("/attachments/{attachmentId}")
    public ResponseVO<Void> delete(@PathVariable Long attachmentId, HttpServletRequest request) {
        attachmentService.delete(attachmentId, request);
        return ResponseVO.success(RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }
}


