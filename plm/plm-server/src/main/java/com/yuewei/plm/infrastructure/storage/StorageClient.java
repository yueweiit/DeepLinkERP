package com.yuewei.plm.infrastructure.storage;

import org.springframework.core.io.Resource;
import org.springframework.web.multipart.MultipartFile;

public interface StorageClient {

    StoredFile store(String folder, MultipartFile file);

    Resource loadAsResource(String storageKey);

    boolean exists(String storageKey);

    void delete(String storageKey);

    String generateDownloadUrl(String storageKey);

    record StoredFile(String storageKey, long fileSize, String checksum) {
    }
}
