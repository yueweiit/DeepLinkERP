package com.yuewei.plm.module.attachment.service;

import org.springframework.core.io.Resource;

public record AttachmentDownloadResource(String fileName, String contentType, Resource resource) {
}
