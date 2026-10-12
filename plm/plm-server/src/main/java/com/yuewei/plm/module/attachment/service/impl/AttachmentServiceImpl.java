package com.yuewei.plm.module.attachment.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.yuewei.plm.common.config.AppProperties;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.common.security.CurrentUserContext;
import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.PageVO;
import com.yuewei.plm.infrastructure.storage.StorageClient;
import com.yuewei.plm.infrastructure.storage.StorageClient.StoredFile;
import com.yuewei.plm.module.attachment.constant.AttachmentOwnerTypeConstants;
import com.yuewei.plm.module.attachment.dto.AttachmentQueryDTO;
import com.yuewei.plm.module.attachment.entity.Attachment;
import com.yuewei.plm.module.attachment.entity.AttachmentDownloadLog;
import com.yuewei.plm.module.attachment.repository.AttachmentDownloadLogRepository;
import com.yuewei.plm.module.attachment.repository.AttachmentRepository;
import com.yuewei.plm.module.attachment.service.AttachmentDownloadResource;
import com.yuewei.plm.module.attachment.service.AttachmentService;
import com.yuewei.plm.module.attachment.vo.AttachmentVO;
import com.yuewei.plm.module.attachment.vo.AttachmentPreviewVO;
import com.yuewei.plm.module.operationlog.constant.OperationActionConstants;
import com.yuewei.plm.module.operationlog.service.OperationLogCreateCommand;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.project.constant.TimelineNodeConstants.TimelineNodeDefinition;
import com.yuewei.plm.module.project.service.TimelineDefinitionProvider;
import com.yuewei.plm.module.project.variant.entity.RequirementForm;
import com.yuewei.plm.module.project.variant.repository.RequirementFormRepository;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import jakarta.servlet.http.HttpServletRequest;
import java.time.LocalDateTime;
import java.util.Arrays;
import java.util.Collections;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;
import java.util.stream.Collectors;
import lombok.RequiredArgsConstructor;
import org.springframework.core.io.Resource;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;
import org.springframework.web.multipart.MultipartFile;

@Service
@RequiredArgsConstructor
public class AttachmentServiceImpl implements AttachmentService {

    private static final String STORAGE_LOCAL = "local";
    private static final String STATUS_DRAFT = "draft";
    private static final String PREVIEW_STATUS_NONE = "none";
    private static final String PREVIEW_STATUS_READY = "ready";
    private static final String PREVIEW_STATUS_UNSUPPORTED = "unsupported";
    private static final Set<String> CATEGORIES = Set.of(
        "sop", "sip", "testing", "drawing", "engineering", "customer_confirm", "sample_image", "other"
    );
    private static final Set<String> IMAGE_EXTENSIONS = Set.of("jpg", "jpeg", "png", "webp");
    private static final Set<String> TEXT_EXTENSIONS = Set.of("txt", "csv");

    private final ProductRepository productRepository;
    private final AttachmentRepository attachmentRepository;
    private final AttachmentDownloadLogRepository attachmentDownloadLogRepository;
    private final TimelineDefinitionProvider timelineDefinitionProvider;
    private final StorageClient storageClient;
    private final AppProperties appProperties;
    private final OperationLogService operationLogService;
    private final RequirementFormRepository requirementFormRepository;

    @Override
    @Transactional
    public AttachmentVO uploadTimelineAttachment(Long projectId, String nodeKey, MultipartFile file, String fileCategory,
                                                 String versionNo, String remark, HttpServletRequest request) {
        Product product = getProductOrThrow(projectId);
        requireTimelineStarted(product);
        TimelineNodeDefinition step = requireValidNode(product, nodeKey);
        requireStepInCurrentStage(product, step);
        return createAttachment(projectId, nodeKey, file, fileCategory, versionNo, remark, request, product, step);
    }

    private void requireTimelineStarted(Product product) {
        if (!"model_variant".equals(product.getProductType())) {
            return;
        }
        RequirementForm form = requirementFormRepository.selectList(new LambdaQueryWrapper<RequirementForm>()
                .eq(RequirementForm::getProjectId, product.getProductId())
                .eq(RequirementForm::getDeletedFlag, 0))
            .stream()
            .findFirst()
            .orElse(null);
        if (form == null || !"confirmed".equals(form.getStatus())) {
            throw new BusinessException(
                ErrorCodeConstants.STATUS_TRANSITION_ILLEGAL,
                "请先完成新型号项目信息完善表，确认后才能上传时间轴资料"
            );
        }
    }

    @Override
    @Transactional
    public AttachmentVO uploadProjectAttachment(Long projectId, MultipartFile file, String fileCategory,
                                                String versionNo, String remark, HttpServletRequest request) {
        Product product = getProductOrThrow(projectId);
        return createAttachment(projectId, null, file, fileCategory, versionNo, remark, request, product, null);
    }

    @Override
    @Transactional
    public AttachmentVO uploadProductAttachment(Long productId, MultipartFile file, String fileCategory,
                                                String versionNo, String remark, HttpServletRequest request) {
        Product product = getProductOrThrow(productId);
        return createAttachment(productId, null, file, fileCategory, versionNo, remark, request, product, null);
    }

    @Override
    public java.util.List<AttachmentVO> listProductAttachments(Long productId, String fileCategory) {
        Product product = getProductOrThrow(productId);
        return attachmentRepository.selectList(baseQuery()
                .eq(Attachment::getOwnerObjectId, productId)
                .eq(StringUtils.hasText(fileCategory), Attachment::getFileCategory, fileCategory)
                .orderByDesc(Attachment::getCreatedAt))
            .stream()
            .map(attachment -> AttachmentVO.from(attachment).withProjectAndStep(product, null))
            .toList();
    }

    private AttachmentVO createAttachment(Long projectId, String nodeKey, MultipartFile file, String fileCategory,
                                          String versionNo, String remark, HttpServletRequest request, Product product,
                                          TimelineNodeDefinition step) {
        requireValidUpload(file, fileCategory);
        String originalName = file.getOriginalFilename();
        String ext = extension(originalName);
        String storageFolder = StringUtils.hasText(nodeKey)
            ? "projects/" + projectId + "/" + nodeKey
            : "projects/" + projectId + "/project-files";
        StoredFile storedFile = storageClient.store(storageFolder, file);
        LocalDateTime now = LocalDateTime.now();
        String operator = currentUserName();
        Attachment attachment = new Attachment();
        attachment.setOwnerObjectType(AttachmentOwnerTypeConstants.PRODUCT);
        attachment.setOwnerObjectId(projectId);
        attachment.setTimelineNodeKey(nodeKey);
        attachment.setFileCategory(fileCategory);
        attachment.setFileName(originalName);
        attachment.setOriginalFileName(originalName);
        attachment.setFileExt(ext);
        attachment.setContentType(file.getContentType());
        attachment.setFileSize(storedFile.fileSize());
        attachment.setChecksum(storedFile.checksum());
        attachment.setStorageType(STORAGE_LOCAL);
        attachment.setStorageKey(storedFile.storageKey());
        attachment.setPreviewType(resolvePreviewType(ext));
        attachment.setPreviewStatus(isPreviewable(attachment.getPreviewType()) ? PREVIEW_STATUS_READY : PREVIEW_STATUS_UNSUPPORTED);
        attachment.setVersionNo(StringUtils.hasText(versionNo) ? versionNo : "V1");
        attachment.setStatus(STATUS_DRAFT);
        attachment.setRemark(remark);
        fillCreateAudit(attachment, now, operator);
        attachmentRepository.insert(attachment);
        writeLog(OperationActionConstants.ATTACHMENT_UPLOAD, attachment, "{\"action\":\"upload\"}", request);
        return AttachmentVO.from(attachment).withProjectAndStep(product, step);
    }

    @Override
    public java.util.List<AttachmentVO> listTimelineAttachments(Long projectId, String nodeKey) {
        Product product = getProductOrThrow(projectId);
        requireValidNode(product, nodeKey);
        return attachmentRepository.selectList(baseQuery()
                .eq(Attachment::getOwnerObjectId, projectId)
                .eq(Attachment::getTimelineNodeKey, nodeKey)
                .orderByDesc(Attachment::getCreatedAt))
            .stream()
            .map(AttachmentVO::from)
            .toList();
    }

    @Override
    public PageVO<AttachmentVO> pageFileCenter(AttachmentQueryDTO queryDTO) {
        long pageNo = queryDTO.getPage() == null || queryDTO.getPage() < 1 ? 1 : queryDTO.getPage();
        long pageSize = queryDTO.getSize() == null || queryDTO.getSize() < 1 ? 20 : Math.min(queryDTO.getSize(), 200);
        LambdaQueryWrapper<Attachment> wrapper = baseQuery()
            .eq(queryDTO.getProjectId() != null, Attachment::getOwnerObjectId, queryDTO.getProjectId())
            .eq(StringUtils.hasText(queryDTO.getNodeKey()), Attachment::getTimelineNodeKey, queryDTO.getNodeKey())
            .eq(StringUtils.hasText(queryDTO.getFileCategory()), Attachment::getFileCategory, queryDTO.getFileCategory())
            .and(StringUtils.hasText(queryDTO.getKeyword()), w -> w
                .like(Attachment::getFileName, queryDTO.getKeyword())
                .or()
                .like(Attachment::getRemark, queryDTO.getKeyword()))
            .orderByDesc(Attachment::getCreatedAt);
        IPage<Attachment> page = attachmentRepository.selectPage(new Page<>(pageNo, pageSize), wrapper);
        return PageVO.<AttachmentVO>builder()
            .content(enrichFileCenterRows(page.getRecords()))
            .page(page.getCurrent())
            .size(page.getSize())
            .totalElements(page.getTotal())
            .totalPages(page.getPages())
            .build();
    }

    @Override
    public AttachmentVO getById(Long attachmentId) {
        return AttachmentVO.from(getAttachmentOrThrow(attachmentId));
    }

    @Override
    public AttachmentPreviewVO previewMetadata(Long attachmentId) {
        Attachment attachment = getAttachmentOrThrow(attachmentId);
        String previewType = resolvePreviewType(attachment);
        boolean previewable = isPreviewable(previewType);
        String previewStatus = resolvePreviewStatus(attachment, previewType);
        return AttachmentPreviewVO.builder()
            .attachmentId(attachment.getAttachmentId())
            .previewable(previewable)
            .previewType(previewType)
            .previewStatus(previewStatus)
            .previewUrl("/api/v1/attachments/" + attachmentId + "/preview")
            .downloadUrl("/api/v1/attachments/" + attachmentId + "/download")
            .message(previewable && PREVIEW_STATUS_READY.equals(previewStatus) ? null : "当前文件类型暂不支持在线预览，请下载后查看")
            .build();
    }

    @Override
    @Transactional
    public AttachmentDownloadResource preview(Long attachmentId, HttpServletRequest request) {
        Attachment attachment = getAttachmentOrThrow(attachmentId);
        String previewType = resolvePreviewType(attachment);
        if (!isPreviewable(previewType)) {
            writeLog(OperationActionConstants.ATTACHMENT_PREVIEW, attachment, "{\"action\":\"preview\",\"status\":\"unsupported\"}", request);
            throw new BusinessException(ErrorCodeConstants.FILE_TYPE_NOT_SUPPORTED, "当前文件类型暂不支持在线预览，请下载后查看");
        }
        String storageKey = StringUtils.hasText(attachment.getPreviewStorageKey())
            ? attachment.getPreviewStorageKey()
            : attachment.getStorageKey();
        Resource resource = storageClient.loadAsResource(storageKey);
        writeLog(OperationActionConstants.ATTACHMENT_PREVIEW, attachment, "{\"action\":\"preview\",\"status\":\"ready\"}", request);
        return new AttachmentDownloadResource(attachment.getOriginalFileName(), resolvePreviewContentType(attachment, previewType), resource);
    }

    @Override
    @Transactional
    public AttachmentDownloadResource download(Long attachmentId, HttpServletRequest request) {
        Attachment attachment = getAttachmentOrThrow(attachmentId);
        Resource resource = storageClient.loadAsResource(attachment.getStorageKey());
        writeDownloadLog(attachment, request);
        writeLog(OperationActionConstants.ATTACHMENT_DOWNLOAD, attachment, "{\"action\":\"download\"}", request);
        return new AttachmentDownloadResource(attachment.getOriginalFileName(), attachment.getContentType(), resource);
    }

    @Override
    @Transactional
    public void delete(Long attachmentId, HttpServletRequest request) {
        Attachment attachment = getAttachmentOrThrow(attachmentId);
        if (attachment.getReleasedAt() != null) {
            throw new BusinessException(ErrorCodeConstants.VERSION_FROZEN, "正式图纸版本必须保留，请上传新版本；不能删除历史正式文件");
        }
        Long references=attachmentRepository.selectCount(new LambdaQueryWrapper<Attachment>()
            .eq(Attachment::getDeletedFlag,0).and(ref -> ref
                .eq(Attachment::getFamilyId,attachmentId).ne(Attachment::getAttachmentId,attachmentId)
                .or().eq(Attachment::getDerivedPdfAttachmentId,attachmentId).isNotNull(Attachment::getReleasedAt)));
        if(references!=null&&references>0)throw new BusinessException(ErrorCodeConstants.VERSION_FROZEN,"此文件是存活版本的族根或正式图纸的 PDF 衍生件，必须随版本族保留");
        attachment.setDeletedFlag(1);
        fillUpdateAudit(attachment);
        attachmentRepository.updateById(attachment);
        writeLog(OperationActionConstants.ATTACHMENT_DELETE, attachment, "{\"action\":\"delete\"}", request);
    }

    private LambdaQueryWrapper<Attachment> baseQuery() {
        return new LambdaQueryWrapper<Attachment>()
            .eq(Attachment::getOwnerObjectType, AttachmentOwnerTypeConstants.PRODUCT)
            .eq(Attachment::getDeletedFlag, 0);
    }

    private Product getProductOrThrow(Long projectId) {
        Product product = productRepository.selectById(projectId);
        if (product == null || Integer.valueOf(1).equals(product.getDeletedFlag())) {
            throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "项目不存在");
        }
        return product;
    }

    private Attachment getAttachmentOrThrow(Long attachmentId) {
        Attachment attachment = attachmentRepository.selectById(attachmentId);
        if (attachment == null || Integer.valueOf(1).equals(attachment.getDeletedFlag())) {
            throw new BusinessException(ErrorCodeConstants.ATTACHMENT_NOT_FOUND, "附件不存在");
        }
        return attachment;
    }

    private TimelineNodeDefinition requireValidNode(Product product, String nodeKey) {
        try {
            return timelineDefinitionProvider.getDefinitionByCode(product, nodeKey);
        } catch (BusinessException ex) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "时间轴节点不存在");
        }
    }

    private void requireStepInCurrentStage(Product product, TimelineNodeDefinition selectedStep) {
        TimelineNodeDefinition currentStep = timelineDefinitionProvider.getDefinitionByStepNo(
            product,
            product.getCurrentStepNo()
        );
        if (!selectedStep.stageCode().equals(currentStep.stageCode())) {
            throw new BusinessException(ErrorCodeConstants.STATUS_TRANSITION_ILLEGAL, "only current stage steps can upload documents");
        }
    }

    private java.util.List<AttachmentVO> enrichFileCenterRows(java.util.List<Attachment> attachments) {
        if (attachments == null || attachments.isEmpty()) {
            return java.util.List.of();
        }
        Set<Long> productIds = attachments.stream()
            .map(Attachment::getOwnerObjectId)
            .filter(id -> id != null)
            .collect(Collectors.toSet());
        Map<Long, Product> productMap = productIds.isEmpty()
            ? Collections.emptyMap()
            : productRepository.selectBatchIds(productIds).stream()
                .collect(Collectors.toMap(Product::getProductId, Function.identity(), (left, right) -> left));

        return attachments.stream()
            .map(attachment -> {
                Product product = productMap.get(attachment.getOwnerObjectId());
                TimelineNodeDefinition step = null;
                if (product != null && StringUtils.hasText(attachment.getTimelineNodeKey())) {
                    try {
                        step = timelineDefinitionProvider.getDefinitionByCode(
                            product,
                            attachment.getTimelineNodeKey()
                        );
                    } catch (BusinessException ignored) {
                        step = null;
                    }
                }
                return AttachmentVO.from(attachment).withProjectAndStep(product, step);
            })
            .toList();
    }

    private void requireValidUpload(MultipartFile file, String fileCategory) {
        if (file == null || file.isEmpty()) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "上传文件不能为空");
        }
        if (!StringUtils.hasText(fileCategory) || !CATEGORIES.contains(fileCategory)) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "文件分类不支持");
        }
        if (file.getSize() > appProperties.getStorage().getMaxFileSizeBytes()) {
            throw new BusinessException(ErrorCodeConstants.FILE_SIZE_EXCEEDED, "文件大小超过限制");
        }
        String ext = extension(file.getOriginalFilename());
        Set<String> allowed = Arrays.stream(appProperties.getStorage().getAllowedExtensions().split(","))
            .map(value -> value.trim().toLowerCase(Locale.ROOT))
            .filter(StringUtils::hasText)
            .collect(Collectors.toSet());
        if (!allowed.contains(ext)) {
            throw new BusinessException(ErrorCodeConstants.FILE_TYPE_NOT_SUPPORTED, "文件类型不支持");
        }
        if ("sample_image".equals(fileCategory) && !IMAGE_EXTENSIONS.contains(ext)) {
            throw new BusinessException(ErrorCodeConstants.FILE_TYPE_NOT_SUPPORTED, "SKU示例照片仅支持jpg、jpeg、png、webp");
        }
    }

    private String extension(String fileName) {
        if (!StringUtils.hasText(fileName) || !fileName.contains(".")) {
            return "";
        }
        return fileName.substring(fileName.lastIndexOf('.') + 1).toLowerCase(Locale.ROOT);
    }

    private String resolvePreviewType(Attachment attachment) {
        if (StringUtils.hasText(attachment.getPreviewType())) {
            return attachment.getPreviewType();
        }
        return resolvePreviewType(attachment.getFileExt());
    }

    private String resolvePreviewType(String ext) {
        String normalized = ext == null ? "" : ext.toLowerCase(Locale.ROOT);
        if (IMAGE_EXTENSIONS.contains(normalized)) return "image";
        if ("pdf".equals(normalized)) return "pdf";
        if (TEXT_EXTENSIONS.contains(normalized)) return "text";
        if (Set.of("doc", "docx", "xls", "xlsx", "ppt", "pptx").contains(normalized)) return "office";
        if (Set.of("dwg", "dxf", "step", "stp", "igs", "iges", "stl", "obj", "3dm", "prt", "sldprt", "sldasm").contains(normalized)) return "cad";
        return "unsupported";
    }

    private String resolvePreviewStatus(Attachment attachment, String previewType) {
        String status = attachment.getPreviewStatus();
        if (isPreviewable(previewType) && (!StringUtils.hasText(status) || PREVIEW_STATUS_NONE.equals(status))) {
            return PREVIEW_STATUS_READY;
        }
        if (StringUtils.hasText(status)) {
            return status;
        }
        return PREVIEW_STATUS_UNSUPPORTED;
    }

    private boolean isPreviewable(String previewType) {
        return "image".equals(previewType) || "pdf".equals(previewType) || "text".equals(previewType);
    }

    private String resolvePreviewContentType(Attachment attachment, String previewType) {
        if ("text".equals(previewType)) {
            return "text/plain;charset=UTF-8";
        }
        if ("pdf".equals(previewType)) {
            return "application/pdf";
        }
        return StringUtils.hasText(attachment.getContentType()) ? attachment.getContentType() : "application/octet-stream";
    }

    private void writeDownloadLog(Attachment attachment, HttpServletRequest request) {
        CurrentUser user = CurrentUserContext.get().orElse(null);
        String operator = currentUserName();
        AttachmentDownloadLog log = new AttachmentDownloadLog();
        log.setAttachmentId(attachment.getAttachmentId());
        log.setOperatorUserId(user == null ? null : user.userId());
        log.setOperatorUserName(user == null ? null : user.displayName());
        log.setRequestId(RequestIdUtil.getRequestId(request));
        log.setClientIp(request == null ? null : request.getRemoteAddr());
        log.setUserAgent(request == null ? null : request.getHeader("User-Agent"));
        fillCreateAudit(log, LocalDateTime.now(), operator);
        attachmentDownloadLogRepository.insert(log);
    }

    private void fillCreateAudit(com.yuewei.plm.repository.entity.BaseEntity entity, LocalDateTime now, String operator) {
        entity.setCreatedAt(now);
        entity.setCreatedBy(operator);
        entity.setUpdatedAt(now);
        entity.setUpdatedBy(operator);
        entity.setDeletedFlag(0);
    }

    private void fillUpdateAudit(com.yuewei.plm.repository.entity.BaseEntity entity) {
        entity.setUpdatedAt(LocalDateTime.now());
        entity.setUpdatedBy(currentUserName());
    }

    private String currentUserName() {
        return CurrentUserContext.get()
            .map(CurrentUser::displayName)
            .filter(StringUtils::hasText)
            .orElse("system");
    }

    private void writeLog(String action, Attachment attachment, String detailJson, HttpServletRequest request) {
        operationLogService.logSuccess(OperationLogCreateCommand.builder()
            .action(action)
            .businessType("ATTACHMENT")
            .businessId(String.valueOf(attachment.getAttachmentId()))
            .businessCode(attachment.getStorageKey())
            .businessName(attachment.getOriginalFileName())
            .detailJson(detailJson)
            .request(request)
            .build());
    }
}
