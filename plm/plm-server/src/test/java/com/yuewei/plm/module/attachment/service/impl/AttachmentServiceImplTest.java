package com.yuewei.plm.module.attachment.service.impl;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.yuewei.plm.common.config.AppProperties;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.vo.PageVO;
import com.yuewei.plm.infrastructure.storage.LocalStorageClient;
import com.yuewei.plm.module.attachment.dto.AttachmentQueryDTO;
import com.yuewei.plm.module.attachment.entity.Attachment;
import com.yuewei.plm.module.attachment.repository.AttachmentDownloadLogRepository;
import com.yuewei.plm.module.attachment.repository.AttachmentRepository;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.project.constant.TimelineNodeConstants;
import com.yuewei.plm.module.project.service.TimelineDefinitionProvider;
import com.yuewei.plm.module.project.variant.entity.RequirementForm;
import com.yuewei.plm.module.project.variant.repository.RequirementFormRepository;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import java.nio.file.Files;
import java.time.LocalDateTime;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;
import org.springframework.mock.web.MockMultipartFile;

class AttachmentServiceImplTest {

    @TempDir
    java.nio.file.Path tempDir;

    @Test
    void uploadTimelineAttachmentWritesMetadataAndLocalFile() {
        AppProperties appProperties = new AppProperties();
        appProperties.getStorage().setLocalRoot(tempDir.toString());
        ProductRepository productRepository = mock(ProductRepository.class);
        AttachmentRepository attachmentRepository = mock(AttachmentRepository.class);
        when(productRepository.selectById(10L)).thenReturn(product(10L, 1));
        when(attachmentRepository.insert(any(Attachment.class))).thenAnswer(invocation -> {
            Attachment inserted = invocation.getArgument(0);
            inserted.setAttachmentId(300L);
            return 1;
        });
        AttachmentServiceImpl service = service(appProperties, productRepository, attachmentRepository);
        MockMultipartFile file = new MockMultipartFile("file", "report.txt", "text/plain", "hello".getBytes());

        var vo = service.uploadTimelineAttachment(
            10L,
            "PRODUCT_LINE_INIT_CREATE",
            file,
            "other",
            "V1",
            "stage init",
            null
        );

        assertThat(vo.getAttachmentId()).isEqualTo(300L);
        assertThat(vo.getFileCategory()).isEqualTo("other");
        assertThat(vo.getPreviewable()).isTrue();
        assertThat(vo.getPreviewType()).isEqualTo("text");
        assertThat(vo.getPreviewStatus()).isEqualTo("ready");
        assertThat(Files.exists(tempDir.resolve(vo.getStorageKey()))).isTrue();
        ArgumentCaptor<Attachment> attachmentCaptor = ArgumentCaptor.forClass(Attachment.class);
        verify(attachmentRepository).insert(attachmentCaptor.capture());
        assertThat(attachmentCaptor.getValue().getOwnerObjectType()).isEqualTo("Product");
        assertThat(attachmentCaptor.getValue().getTimelineNodeKey()).isEqualTo("PRODUCT_LINE_INIT_CREATE");
    }

    @Test
    void uploadProjectAttachmentWritesProductFileWithoutTimelineNode() {
        AppProperties appProperties = new AppProperties();
        appProperties.getStorage().setLocalRoot(tempDir.toString());
        ProductRepository productRepository = mock(ProductRepository.class);
        AttachmentRepository attachmentRepository = mock(AttachmentRepository.class);
        when(productRepository.selectById(10L)).thenReturn(product(10L, 1));
        when(attachmentRepository.insert(any(Attachment.class))).thenAnswer(invocation -> {
            Attachment inserted = invocation.getArgument(0);
            inserted.setAttachmentId(301L);
            return 1;
        });
        AttachmentServiceImpl service = service(appProperties, productRepository, attachmentRepository);
        MockMultipartFile file = new MockMultipartFile("file", "project-file.txt", "text/plain", "hello".getBytes());

        var vo = service.uploadProjectAttachment(
            10L,
            file,
            "other",
            "V1",
            "project file",
            null
        );

        assertThat(vo.getAttachmentId()).isEqualTo(301L);
        assertThat(vo.getProjectId()).isEqualTo(10L);
        assertThat(vo.getTimelineNodeKey()).isNull();
        assertThat(Files.exists(tempDir.resolve(vo.getStorageKey()))).isTrue();
        assertThat(vo.getStorageKey()).contains("projects/10/project-files");
        ArgumentCaptor<Attachment> attachmentCaptor = ArgumentCaptor.forClass(Attachment.class);
        verify(attachmentRepository).insert(attachmentCaptor.capture());
        assertThat(attachmentCaptor.getValue().getOwnerObjectType()).isEqualTo("Product");
        assertThat(attachmentCaptor.getValue().getOwnerObjectId()).isEqualTo(10L);
        assertThat(attachmentCaptor.getValue().getTimelineNodeKey()).isNull();
    }

    @Test
    void uploadProjectEngineeringCadFileStoresButMarksPreviewUnsupported() {
        AppProperties appProperties = new AppProperties();
        appProperties.getStorage().setLocalRoot(tempDir.toString());
        ProductRepository productRepository = mock(ProductRepository.class);
        AttachmentRepository attachmentRepository = mock(AttachmentRepository.class);
        when(productRepository.selectById(10L)).thenReturn(product(10L, 1));
        when(attachmentRepository.insert(any(Attachment.class))).thenAnswer(invocation -> {
            Attachment inserted = invocation.getArgument(0);
            inserted.setAttachmentId(302L);
            return 1;
        });
        AttachmentServiceImpl service = service(appProperties, productRepository, attachmentRepository);
        MockMultipartFile file = new MockMultipartFile("file", "mold.step", "application/step", "cad".getBytes());

        var vo = service.uploadProjectAttachment(10L, file, "engineering", "V1", "mold file", null);

        assertThat(vo.getAttachmentId()).isEqualTo(302L);
        assertThat(vo.getFileCategory()).isEqualTo("engineering");
        assertThat(vo.getPreviewable()).isFalse();
        assertThat(vo.getPreviewType()).isEqualTo("cad");
        assertThat(vo.getPreviewStatus()).isEqualTo("unsupported");
        assertThat(Files.exists(tempDir.resolve(vo.getStorageKey()))).isTrue();
    }

    @Test
    void uploadTimelineAttachmentRejectsStepOutsideCurrentStage() {
        AppProperties appProperties = new AppProperties();
        appProperties.getStorage().setLocalRoot(tempDir.toString());
        ProductRepository productRepository = mock(ProductRepository.class);
        AttachmentRepository attachmentRepository = mock(AttachmentRepository.class);
        when(productRepository.selectById(10L)).thenReturn(product(10L, 1));
        AttachmentServiceImpl service = service(appProperties, productRepository, attachmentRepository);
        MockMultipartFile file = new MockMultipartFile("file", "report.txt", "text/plain", "hello".getBytes());

        assertThatThrownBy(() -> service.uploadTimelineAttachment(
            10L,
            "PRODUCT_LINE_DESIGN_DRAWING",
            file,
            "drawing",
            "V1",
            "wrong stage",
            null
        ))
            .isInstanceOf(BusinessException.class)
            .extracting("code")
            .isEqualTo(ErrorCodeConstants.STATUS_TRANSITION_ILLEGAL);
    }

    @Test
    void uploadTimelineAttachmentIsBlockedBeforeModelVariantRequirementFormConfirmation() {
        AppProperties appProperties = new AppProperties();
        appProperties.getStorage().setLocalRoot(tempDir.toString());
        ProductRepository productRepository = mock(ProductRepository.class);
        AttachmentRepository attachmentRepository = mock(AttachmentRepository.class);
        RequirementFormRepository requirementFormRepository = mock(RequirementFormRepository.class);
        Product product = product(10L, 1);
        product.setProductType(TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT);
        when(productRepository.selectById(10L)).thenReturn(product);
        RequirementForm form = new RequirementForm();
        form.setProjectId(10L);
        form.setStatus("draft");
        form.setDeletedFlag(0);
        when(requirementFormRepository.selectList(Mockito.any())).thenReturn(List.of(form));
        AttachmentServiceImpl service = service(appProperties, productRepository, attachmentRepository, requirementFormRepository);
        MockMultipartFile file = new MockMultipartFile("file", "report.txt", "text/plain", "hello".getBytes());

        assertThatThrownBy(() -> service.uploadTimelineAttachment(
            10L,
            "MODEL_VARIANT_INIT_CREATE",
            file,
            "other",
            "V1",
            "blocked",
            null
        ))
            .isInstanceOf(BusinessException.class)
            .hasMessageContaining("请先完成新型号项目信息完善表");
    }

    @Test
    void pageFileCenterEnrichesProjectAndTimelineFields() {
        AppProperties appProperties = new AppProperties();
        appProperties.getStorage().setLocalRoot(tempDir.toString());
        ProductRepository productRepository = mock(ProductRepository.class);
        AttachmentRepository attachmentRepository = mock(AttachmentRepository.class);
        Page<Attachment> page = new Page<>(1, 20);
        page.setRecords(List.of(attachment(300L, 10L, "PRODUCT_LINE_INIT_CREATE", "other")));
        page.setTotal(1);
        when(attachmentRepository.selectPage(any(Page.class), anyWrapper())).thenReturn(page);
        when(productRepository.selectBatchIds(any())).thenReturn(List.of(product(10L, 1)));
        AttachmentServiceImpl service = service(appProperties, productRepository, attachmentRepository);

        AttachmentQueryDTO queryDTO = new AttachmentQueryDTO();
        queryDTO.setPage(1L);
        queryDTO.setSize(20L);
        PageVO<?> result = service.pageFileCenter(queryDTO);

        assertThat(result.getContent()).hasSize(1);
        Object row = result.getContent().get(0);
        assertThat(row).hasFieldOrPropertyWithValue("projectId", 10L);
        assertThat(row).hasFieldOrPropertyWithValue("projectCode", "PRD-CD30-0001");
        assertThat(row).hasFieldOrPropertyWithValue("projectName", "Super Captain 3.0");
        assertThat(row).hasFieldOrPropertyWithValue("timelineStageCode", "PRODUCT_LINE_INIT_CONFIRM");
        assertThat(row).hasFieldOrPropertyWithValue("timelineStepCode", "PRODUCT_LINE_INIT_CREATE");
    }

    @Test
    void downloadMissingLocalFileReturnsExplicitError() {
        AppProperties appProperties = new AppProperties();
        appProperties.getStorage().setLocalRoot(tempDir.toString());
        AttachmentRepository attachmentRepository = mock(AttachmentRepository.class);
        Attachment attachment = new Attachment();
        attachment.setAttachmentId(300L);
        attachment.setOriginalFileName("missing.txt");
        attachment.setStorageKey("missing/missing.txt");
        attachment.setDeletedFlag(0);
        when(attachmentRepository.selectById(300L)).thenReturn(attachment);
        AttachmentServiceImpl service = service(appProperties, mock(ProductRepository.class), attachmentRepository);

        assertThatThrownBy(() -> service.download(300L, null))
            .isInstanceOf(BusinessException.class)
            .extracting("code")
            .isEqualTo(ErrorCodeConstants.FILE_SERVICE_ERROR);
    }

    @Test
    void previewMetadataTreatsLegacyPdfNoneStatusAsReady() {
        AppProperties appProperties = new AppProperties();
        appProperties.getStorage().setLocalRoot(tempDir.toString());
        AttachmentRepository attachmentRepository = mock(AttachmentRepository.class);
        Attachment attachment = attachment(300L, 10L, null, "drawing");
        attachment.setOriginalFileName("drawing.pdf");
        attachment.setFileName("drawing.pdf");
        attachment.setFileExt("pdf");
        attachment.setPreviewType(null);
        attachment.setPreviewStatus("none");
        when(attachmentRepository.selectById(300L)).thenReturn(attachment);
        AttachmentServiceImpl service = service(appProperties, mock(ProductRepository.class), attachmentRepository);

        var metadata = service.previewMetadata(300L);

        assertThat(metadata.getPreviewable()).isTrue();
        assertThat(metadata.getPreviewType()).isEqualTo("pdf");
        assertThat(metadata.getPreviewStatus()).isEqualTo("ready");
        assertThat(metadata.getMessage()).isNull();
        attachment.setReleasedAt(LocalDateTime.now());
        assertThatThrownBy(() -> service.delete(300L, null)).hasMessageContaining("正式图纸版本必须保留");
        attachment.setReleasedAt(null);
        when(attachmentRepository.selectCount(anyWrapper())).thenReturn(1L);
        assertThatThrownBy(() -> service.delete(300L, null)).hasMessageContaining("族根").hasMessageContaining("PDF");
        verify(attachmentRepository, Mockito.never()).updateById(any(Attachment.class));
    }

    private AttachmentServiceImpl service(AppProperties appProperties,
                                          ProductRepository productRepository,
                                          AttachmentRepository attachmentRepository) {
        return service(appProperties, productRepository, attachmentRepository, mock(RequirementFormRepository.class));
    }

    private AttachmentServiceImpl service(AppProperties appProperties,
                                          ProductRepository productRepository,
                                          AttachmentRepository attachmentRepository,
                                          RequirementFormRepository requirementFormRepository) {
        return new AttachmentServiceImpl(
            productRepository,
            attachmentRepository,
            mock(AttachmentDownloadLogRepository.class),
            new TimelineDefinitionProvider(),
            new LocalStorageClient(appProperties),
            appProperties,
            mock(OperationLogService.class),
            requirementFormRepository
        );
    }

    private Product product(Long productId, Integer currentStepNo) {
        Product product = new Product();
        product.setProductId(productId);
        product.setProductCode("PRD-CD30-0001");
        product.setProductName("Super Captain 3.0");
        product.setProductType(TimelineNodeConstants.PRODUCT_TYPE_PRODUCT_LINE);
        product.setCurrentStepNo(currentStepNo);
        product.setDeletedFlag(0);
        return product;
    }

    private Attachment attachment(Long attachmentId, Long projectId, String nodeKey, String category) {
        Attachment attachment = new Attachment();
        attachment.setAttachmentId(attachmentId);
        attachment.setOwnerObjectType("Product");
        attachment.setOwnerObjectId(projectId);
        attachment.setTimelineNodeKey(nodeKey);
        attachment.setFileCategory(category);
        attachment.setFileName("report.txt");
        attachment.setOriginalFileName("report.txt");
        attachment.setFileExt("txt");
        attachment.setContentType("text/plain");
        attachment.setFileSize(5L);
        attachment.setChecksum("checksum");
        attachment.setStorageType("local");
        attachment.setStorageKey("projects/10/report.txt");
        attachment.setVersionNo("V1");
        attachment.setStatus("draft");
        attachment.setCreatedAt(LocalDateTime.now());
        attachment.setCreatedBy("Engineer One");
        attachment.setDeletedFlag(0);
        return attachment;
    }

    @SuppressWarnings("unchecked")
    private Wrapper<Attachment> anyWrapper() {
        return any(Wrapper.class);
    }
}
