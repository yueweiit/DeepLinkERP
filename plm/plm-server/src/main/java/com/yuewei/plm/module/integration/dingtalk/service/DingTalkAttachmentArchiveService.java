package com.yuewei.plm.module.integration.dingtalk.service;

import com.yuewei.plm.module.attachment.constant.AttachmentOwnerTypeConstants;
import com.yuewei.plm.module.attachment.entity.Attachment;
import com.yuewei.plm.module.attachment.repository.AttachmentRepository;
import com.yuewei.plm.module.integration.dingtalk.dto.DingTalkAttachmentDTO;
import com.yuewei.plm.module.operationlog.constant.OperationActionConstants;
import com.yuewei.plm.module.operationlog.service.OperationLogCreateCommand;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.repository.entity.Product;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Locale;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

@Service
@RequiredArgsConstructor
public class DingTalkAttachmentArchiveService {
    private static final String STORAGE_DINGTALK = "dingtalk";
    private static final String STATUS_DRAFT = "draft";
    private static final String PREVIEW_UNSUPPORTED = "unsupported";

    private final AttachmentRepository attachmentRepository;
    private final OperationLogService operationLogService;

    @Transactional
    public String archiveMetadata(List<DingTalkAttachmentDTO> attachments, Product product, String nodeKey,
                                  String fileCategory, String operator) {
        if (attachments == null || attachments.isEmpty()) {
            return "not_provided";
        }
        String createdBy = StringUtils.hasText(operator) ? operator : "dingtalk";
        int archived = 0;
        for (DingTalkAttachmentDTO source : attachments) {
            if (source == null || (!StringUtils.hasText(source.getFileId()) && !StringUtils.hasText(source.getFileName()))) {
                continue;
            }
            Attachment attachment = new Attachment();
            attachment.setOwnerObjectType(AttachmentOwnerTypeConstants.PRODUCT);
            attachment.setOwnerObjectId(product.getProductId());
            attachment.setTimelineNodeKey(nodeKey);
            attachment.setFileCategory(StringUtils.hasText(fileCategory) ? fileCategory : "other");
            attachment.setFileName(resolveFileName(source));
            attachment.setOriginalFileName(resolveFileName(source));
            attachment.setFileExt(extension(source.getFileName()));
            attachment.setContentType(source.getContentType());
            attachment.setFileSize(source.getFileSize());
            attachment.setStorageType(STORAGE_DINGTALK);
            attachment.setStorageKey(resolveStorageKey(source));
            attachment.setPreviewType(PREVIEW_UNSUPPORTED);
            attachment.setPreviewStatus(PREVIEW_UNSUPPORTED);
            attachment.setSourceSystem("dingtalk");
            attachment.setSourceFileId(source.getFileId());
            attachment.setSourceUrl(source.getDownloadUrl());
            attachment.setVersionNo("V1");
            attachment.setStatus(STATUS_DRAFT);
            attachment.setRemark("钉钉审批附件元数据归档，待文件下载权限确认后可增强为文件入库");
            fill(attachment, createdBy);
            attachmentRepository.insert(attachment);
            archived++;
        }
        if (archived > 0) {
            writeLog(product, archived);
        }
        return archived > 0 ? "archived_metadata" : "not_provided";
    }

    private String resolveFileName(DingTalkAttachmentDTO source) {
        if (StringUtils.hasText(source.getFileName())) {
            return source.getFileName().trim();
        }
        return source.getFileId().trim();
    }

    private String resolveStorageKey(DingTalkAttachmentDTO source) {
        if (StringUtils.hasText(source.getDownloadUrl())) {
            return source.getDownloadUrl().trim();
        }
        return "dingtalk://" + source.getFileId();
    }

    private String extension(String fileName) {
        if (!StringUtils.hasText(fileName) || !fileName.contains(".")) {
            return "";
        }
        return fileName.substring(fileName.lastIndexOf('.') + 1).toLowerCase(Locale.ROOT);
    }

    private void fill(Attachment attachment, String operator) {
        LocalDateTime now = LocalDateTime.now();
        attachment.setCreatedAt(now);
        attachment.setCreatedBy(operator);
        attachment.setUpdatedAt(now);
        attachment.setUpdatedBy(operator);
        attachment.setDeletedFlag(0);
    }

    private void writeLog(Product product, int archived) {
        operationLogService.logSuccess(OperationLogCreateCommand.builder()
            .action(OperationActionConstants.DINGTALK_ATTACHMENT_ARCHIVE)
            .businessType("PRODUCT")
            .businessId(String.valueOf(product.getProductId()))
            .businessCode(product.getProductCode())
            .businessName(product.getProductName())
            .detailJson("{\"action\":\"archive_dingtalk_attachment_metadata\",\"archived\":" + archived + "}")
            .build());
    }
}
