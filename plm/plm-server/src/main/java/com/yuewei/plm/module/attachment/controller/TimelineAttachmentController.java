package com.yuewei.plm.module.attachment.controller;

import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.attachment.service.AttachmentService;
import com.yuewei.plm.module.attachment.vo.AttachmentVO;
import jakarta.servlet.http.HttpServletRequest;
import java.time.OffsetDateTime;
import java.util.List;
import lombok.RequiredArgsConstructor;
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
public class TimelineAttachmentController {

    private final AttachmentService attachmentService;

    @PostMapping("/projects/{projectId}/timeline/{nodeKey}/attachments")
    public ResponseVO<AttachmentVO> upload(@PathVariable Long projectId,
                                           @PathVariable String nodeKey,
                                           @RequestParam("file") MultipartFile file,
                                           @RequestParam String fileCategory,
                                           @RequestParam(required = false) String versionNo,
                                           @RequestParam(required = false) String remark,
                                           HttpServletRequest request) {
        return ResponseVO.success(
            attachmentService.uploadTimelineAttachment(projectId, nodeKey, file, fileCategory, versionNo, remark, request),
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }

    @PostMapping("/projects/{projectId}/attachments")
    public ResponseVO<AttachmentVO> uploadProjectFile(@PathVariable Long projectId,
                                                      @RequestParam("file") MultipartFile file,
                                                      @RequestParam String fileCategory,
                                                      @RequestParam(required = false) String versionNo,
                                                      @RequestParam(required = false) String remark,
                                                      HttpServletRequest request) {
        return ResponseVO.success(
            attachmentService.uploadProjectAttachment(projectId, file, fileCategory, versionNo, remark, request),
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }

    @GetMapping("/projects/{projectId}/timeline/{nodeKey}/attachments")
    public ResponseVO<List<AttachmentVO>> list(@PathVariable Long projectId,
                                               @PathVariable String nodeKey,
                                               HttpServletRequest request) {
        return ResponseVO.success(
            attachmentService.listTimelineAttachments(projectId, nodeKey),
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }
}
