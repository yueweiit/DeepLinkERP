package com.yuewei.plm.module.attachment.vo;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class AttachmentPreviewVO {
    private Long attachmentId;
    private Boolean previewable;
    private String previewType;
    private String previewStatus;
    private String previewUrl;
    private String downloadUrl;
    private String message;
}
