package com.yuewei.plm.module.attachment.service;

import com.yuewei.plm.common.vo.PageVO;
import com.yuewei.plm.module.attachment.dto.AttachmentQueryDTO;
import com.yuewei.plm.module.attachment.vo.AttachmentVO;
import com.yuewei.plm.module.attachment.vo.AttachmentPreviewVO;
import jakarta.servlet.http.HttpServletRequest;
import java.util.List;
import org.springframework.web.multipart.MultipartFile;

public interface AttachmentService {

    AttachmentVO uploadTimelineAttachment(Long projectId, String nodeKey, MultipartFile file, String fileCategory,
                                           String versionNo, String remark, HttpServletRequest request);

    AttachmentVO uploadProjectAttachment(Long projectId, MultipartFile file, String fileCategory,
                                         String versionNo, String remark, HttpServletRequest request);

    AttachmentVO uploadProductAttachment(Long productId, MultipartFile file, String fileCategory,
                                         String versionNo, String remark, HttpServletRequest request);

    List<AttachmentVO> listProductAttachments(Long productId, String fileCategory);

    List<AttachmentVO> listTimelineAttachments(Long projectId, String nodeKey);

    PageVO<AttachmentVO> pageFileCenter(AttachmentQueryDTO queryDTO);

    AttachmentVO getById(Long attachmentId);

    AttachmentPreviewVO previewMetadata(Long attachmentId);

    AttachmentDownloadResource preview(Long attachmentId, HttpServletRequest request);

    AttachmentDownloadResource download(Long attachmentId, HttpServletRequest request);

    void delete(Long attachmentId, HttpServletRequest request);
}


