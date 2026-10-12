package com.yuewei.plm.module.integration.dingtalk.dto;

import lombok.Data;

@Data
public class DingTalkAttachmentDTO {
    private String fileId;
    private String fileName;
    private String downloadUrl;
    private String contentType;
    private Long fileSize;
}
