package com.yuewei.plm.module.attachment.controller;

import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.PageVO;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.attachment.dto.AttachmentQueryDTO;
import com.yuewei.plm.module.attachment.service.AttachmentService;
import com.yuewei.plm.module.attachment.vo.AttachmentVO;
import jakarta.servlet.http.HttpServletRequest;
import java.time.OffsetDateTime;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.ModelAttribute;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
@RequestMapping("/api/v1")
public class FileCenterController {

    private final AttachmentService attachmentService;

    @GetMapping("/file-center/attachments")
    public ResponseVO<PageVO<AttachmentVO>> page(@ModelAttribute AttachmentQueryDTO queryDTO,
                                                 HttpServletRequest request) {
        return ResponseVO.success(
            attachmentService.pageFileCenter(queryDTO),
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }
}
