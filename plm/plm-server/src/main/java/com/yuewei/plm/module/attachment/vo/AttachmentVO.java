package com.yuewei.plm.module.attachment.vo;

import com.yuewei.plm.module.attachment.entity.Attachment;
import com.yuewei.plm.module.project.constant.TimelineNodeConstants.TimelineNodeDefinition;
import com.yuewei.plm.repository.entity.Product;
import java.time.LocalDateTime;
import java.util.Locale;
import java.util.Set;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class AttachmentVO {

    private Long attachmentId;
    private String ownerObjectType;
    private Long ownerObjectId;
    private Long projectId;
    private String projectCode;
    private String projectName;
    private String timelineNodeKey;
    private String timelineStageCode;
    private String timelineStageName;
    private String timelineStepCode;
    private String timelineStepName;
    private String fileCategory;
    private String fileName;
    private String originalFileName;
    private String fileExt;
    private String contentType;
    private Long fileSize;
    private String checksum;
    private String storageType;
    private String storageKey;
    private Boolean previewable;
    private String previewType;
    private String previewStatus;
    private String previewUrl;
    private String downloadUrl;
    private String previewErrorMessage;
    private String versionNo;
    private String status;
    private String remark;
    private Long familyId;
    private String changeReason;
    private LocalDateTime releasedAt;
    private String releasedBy;
    private Long releasedByUserId;
    private Long collaborationItemId;
    private Long moldSetId;
    private Long derivedPdfAttachmentId;
    private LocalDateTime createdAt;
    private String createdBy;

    private static final Set<String> IMAGE_EXTENSIONS = Set.of("jpg", "jpeg", "png", "webp");
    private static final Set<String> TEXT_EXTENSIONS = Set.of("txt", "csv");

    public static AttachmentVO from(Attachment attachment) {
        return AttachmentVO.builder()
            .attachmentId(attachment.getAttachmentId())
            .ownerObjectType(attachment.getOwnerObjectType())
            .ownerObjectId(attachment.getOwnerObjectId())
            .timelineNodeKey(attachment.getTimelineNodeKey())
            .fileCategory(attachment.getFileCategory())
            .fileName(attachment.getFileName())
            .originalFileName(attachment.getOriginalFileName())
            .fileExt(attachment.getFileExt())
            .contentType(attachment.getContentType())
            .fileSize(attachment.getFileSize())
            .checksum(attachment.getChecksum())
            .storageType(attachment.getStorageType())
            .storageKey(attachment.getStorageKey())
            .previewable(isPreviewable(resolvePreviewType(attachment)))
            .previewType(resolvePreviewType(attachment))
            .previewStatus(resolvePreviewStatus(attachment))
            .previewUrl("/api/v1/attachments/" + attachment.getAttachmentId() + "/preview")
            .downloadUrl("/api/v1/attachments/" + attachment.getAttachmentId() + "/download")
            .previewErrorMessage(attachment.getPreviewErrorMessage())
            .versionNo(attachment.getVersionNo())
            .status(attachment.getStatus())
            .remark(attachment.getRemark())
            .familyId(attachment.getFamilyId())
            .changeReason(attachment.getChangeReason())
            .releasedAt(attachment.getReleasedAt())
            .releasedBy(attachment.getReleasedBy())
            .releasedByUserId(attachment.getReleasedByUserId())
            .collaborationItemId(attachment.getCollaborationItemId())
            .moldSetId(attachment.getMoldSetId())
            .derivedPdfAttachmentId(attachment.getDerivedPdfAttachmentId())
            .createdAt(attachment.getCreatedAt())
            .createdBy(attachment.getCreatedBy())
            .build();
    }

    private static String resolvePreviewType(Attachment attachment) {
        if (attachment.getPreviewType() != null && !attachment.getPreviewType().isBlank()) {
            return attachment.getPreviewType();
        }
        String ext = attachment.getFileExt() == null ? "" : attachment.getFileExt().toLowerCase(Locale.ROOT);
        if (IMAGE_EXTENSIONS.contains(ext)) return "image";
        if ("pdf".equals(ext)) return "pdf";
        if (TEXT_EXTENSIONS.contains(ext)) return "text";
        if (Set.of("doc", "docx", "xls", "xlsx", "ppt", "pptx").contains(ext)) return "office";
        if (Set.of("dwg", "dxf", "step", "stp", "igs", "iges", "stl", "obj", "3dm", "prt", "sldprt", "sldasm").contains(ext)) return "cad";
        return "unsupported";
    }

    private static String resolvePreviewStatus(Attachment attachment) {
        String previewType = resolvePreviewType(attachment);
        String previewStatus = attachment.getPreviewStatus();
        if (isPreviewable(previewType) && (previewStatus == null || previewStatus.isBlank() || "none".equals(previewStatus))) {
            return "ready";
        }
        if (previewStatus != null && !previewStatus.isBlank()) {
            return previewStatus;
        }
        return "unsupported";
    }

    private static boolean isPreviewable(String previewType) {
        return "image".equals(previewType) || "pdf".equals(previewType) || "text".equals(previewType);
    }

    public AttachmentVO withProjectAndStep(Product product, TimelineNodeDefinition step) {
        this.projectId = ownerObjectId;
        if (product != null) {
            this.projectCode = product.getProductCode();
            this.projectName = product.getProductName();
        }
        if (step != null) {
            this.timelineStageCode = step.stageCode();
            this.timelineStageName = step.stageName();
            this.timelineStepCode = step.nodeCode();
            this.timelineStepName = step.nodeName();
        }
        return this;
    }
}
