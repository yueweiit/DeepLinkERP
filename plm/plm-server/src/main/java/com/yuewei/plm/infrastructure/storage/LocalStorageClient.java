package com.yuewei.plm.infrastructure.storage;

import com.yuewei.plm.common.config.AppProperties;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.DigestInputStream;
import java.security.MessageDigest;
import java.time.LocalDate;
import java.util.HexFormat;
import java.util.UUID;
import lombok.RequiredArgsConstructor;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.Resource;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.multipart.MultipartFile;

@Component
@RequiredArgsConstructor
public class LocalStorageClient implements StorageClient {

    private final AppProperties appProperties;

    @Override
    public StoredFile store(String folder, MultipartFile file) {
        try {
            Path root = Path.of(appProperties.getStorage().getLocalRoot()).toAbsolutePath().normalize();
            String ext = extension(file.getOriginalFilename());
            String datePath = LocalDate.now().toString().replace("-", "");
            String fileName = UUID.randomUUID() + (StringUtils.hasText(ext) ? "." + ext : "");
            String storageKey = sanitize(folder) + "/" + datePath + "/" + fileName;
            Path target = root.resolve(storageKey).normalize();
            if (!target.startsWith(root)) {
                throw new BusinessException(ErrorCodeConstants.FILE_SERVICE_ERROR, "非法文件存储路径");
            }
            Files.createDirectories(target.getParent());
            String checksum = writeAndChecksum(file, target);
            return new StoredFile(storageKey, file.getSize(), checksum);
        } catch (BusinessException ex) {
            throw ex;
        } catch (Exception ex) {
            throw new BusinessException(ErrorCodeConstants.FILE_SERVICE_ERROR, "文件保存失败");
        }
    }

    @Override
    public Resource loadAsResource(String storageKey) {
        Path path = resolve(storageKey);
        if (!Files.exists(path) || !Files.isRegularFile(path)) {
            throw new BusinessException(ErrorCodeConstants.FILE_SERVICE_ERROR, "附件元数据存在，但本机文件已丢失");
        }
        return new FileSystemResource(path);
    }

    @Override
    public boolean exists(String storageKey) {
        Path path = resolve(storageKey);
        return Files.exists(path) && Files.isRegularFile(path);
    }

    @Override
    public void delete(String storageKey) {
        try {
            Files.deleteIfExists(resolve(storageKey));
        } catch (IOException ex) {
            throw new BusinessException(ErrorCodeConstants.FILE_SERVICE_ERROR, "文件删除失败");
        }
    }

    @Override
    public String generateDownloadUrl(String storageKey) {
        return "/api/v1/attachments/download?storageKey=" + storageKey;
    }

    private Path resolve(String storageKey) {
        Path root = Path.of(appProperties.getStorage().getLocalRoot()).toAbsolutePath().normalize();
        Path path = root.resolve(storageKey).normalize();
        if (!path.startsWith(root)) {
            throw new BusinessException(ErrorCodeConstants.FILE_SERVICE_ERROR, "非法文件存储路径");
        }
        return path;
    }

    private String writeAndChecksum(MultipartFile file, Path target) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream inputStream = file.getInputStream();
             DigestInputStream digestInputStream = new DigestInputStream(inputStream, digest)) {
            Files.copy(digestInputStream, target);
        }
        return HexFormat.of().formatHex(digest.digest());
    }

    private String extension(String fileName) {
        if (!StringUtils.hasText(fileName) || !fileName.contains(".")) {
            return "";
        }
        return fileName.substring(fileName.lastIndexOf('.') + 1).toLowerCase();
    }

    private String sanitize(String value) {
        if (!StringUtils.hasText(value)) {
            return "attachments";
        }
        return value.replace("\\", "/").replaceAll("[^a-zA-Z0-9/_-]", "_");
    }
}
