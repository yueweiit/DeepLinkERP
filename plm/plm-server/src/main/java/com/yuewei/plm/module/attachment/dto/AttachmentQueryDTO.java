package com.yuewei.plm.module.attachment.dto;

import lombok.Data;

@Data
public class AttachmentQueryDTO {

    private Long projectId;
    private String nodeKey;
    private String fileCategory;
    private String keyword;
    private Long page = 1L;
    private Long size = 20L;
}
