package com.yuewei.plm.module.attachment.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.yuewei.plm.repository.entity.BaseEntity;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@TableName("plm_attachment_download_log")
@EqualsAndHashCode(callSuper = true)
public class AttachmentDownloadLog extends BaseEntity {

    @TableId(value = "download_log_id", type = IdType.AUTO)
    private Long downloadLogId;
    private Long attachmentId;
    private Long operatorUserId;
    private String operatorUserName;
    private String requestId;
    private String clientIp;
    private String userAgent;
}
