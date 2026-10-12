package com.yuewei.plm.service.impl;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.yuewei.plm.module.attachment.entity.Attachment;
import com.yuewei.plm.module.attachment.repository.AttachmentRepository;
import com.yuewei.plm.module.bom.entity.ProductBom;
import com.yuewei.plm.module.bom.repository.ProductBomRepository;
import com.yuewei.plm.module.process.entity.ProcessEntity;
import com.yuewei.plm.module.process.repository.ProcessRepository;
import com.yuewei.plm.module.project.service.TimelineDefinitionProvider;
import com.yuewei.plm.repository.entity.Product;
import org.junit.jupiter.api.Test;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;

class ProductReleaseGateValidatorImplTest {

    @Test
    void checkReturnsMissingItemsWhenReleaseMaterialsAreIncomplete() {
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProcessRepository processRepository = mock(ProcessRepository.class);
        AttachmentRepository attachmentRepository = mock(AttachmentRepository.class);
        ProductReleaseGateValidatorImpl validator = new ProductReleaseGateValidatorImpl(
            bomRepository,
            processRepository,
            attachmentRepository,
            new TimelineDefinitionProvider()
        );
        Product product = releasableProduct();
        product.setStatus("developing");
        product.setCurrentStepNo(4);
        product.setTimelineCurrentConfirmed(false);
        product.setTimelineConfirmedNodeKey(null);
        when(bomRepository.selectCount(Mockito.<Wrapper<ProductBom>>any())).thenReturn(0L);
        when(processRepository.selectCount(Mockito.<Wrapper<ProcessEntity>>any())).thenReturn(0L);
        when(attachmentRepository.selectCount(Mockito.<Wrapper<Attachment>>any()))
            .thenReturn(0L, 0L, 0L, 0L);

        var result = validator.check(product);

        assertThat(result.getPassed()).isFalse();
        assertThat(result.getMissingItems())
            .extracting("code")
            .contains(
                "TIMELINE_NODE_NOT_ALLOWED",
                "TIMELINE_NODE_NOT_CONFIRMED",
                "BOM_NOT_FROZEN",
                "PROCESS_ROUTE_NOT_LOCKED",
                "DRAWING_FILE_MISSING",
                "SOP_OR_SIP_FILE_MISSING",
                "TESTING_FILE_MISSING"
            );
    }

    @Test
    void checkPassesWhenBomProcessFilesAndTimelineAreReady() {
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProcessRepository processRepository = mock(ProcessRepository.class);
        AttachmentRepository attachmentRepository = mock(AttachmentRepository.class);
        ProductReleaseGateValidatorImpl validator = new ProductReleaseGateValidatorImpl(
            bomRepository,
            processRepository,
            attachmentRepository,
            new TimelineDefinitionProvider()
        );
        when(bomRepository.selectCount(Mockito.<Wrapper<ProductBom>>any())).thenReturn(1L);
        when(processRepository.selectCount(Mockito.<Wrapper<ProcessEntity>>any())).thenReturn(1L);
        when(attachmentRepository.selectCount(Mockito.<Wrapper<Attachment>>any()))
            .thenReturn(1L, 1L, 0L, 1L);

        var result = validator.check(releasableProduct());

        assertThat(result.getPassed()).isTrue();
        assertThat(result.getMissingItems()).isEmpty();
        assertThat(result.getFrozenBomCount()).isEqualTo(1);
        assertThat(result.getLockedProcessRouteCount()).isEqualTo(1);
        assertThat(result.getDrawingFileCount()).isEqualTo(1);
        assertThat(result.getSopFileCount() + result.getSipFileCount()).isGreaterThanOrEqualTo(1);
        assertThat(result.getTestingFileCount()).isEqualTo(1);
        ArgumentCaptor<Wrapper<Attachment>> wrapperCaptor = ArgumentCaptor.forClass(Wrapper.class);
        verify(attachmentRepository, times(4)).selectCount(wrapperCaptor.capture());
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(new MybatisConfiguration(), "test"), Attachment.class);
        assertThat(wrapperCaptor.getAllValues())
            .allSatisfy(wrapper -> {
                LambdaQueryWrapper<Attachment> queryWrapper = (LambdaQueryWrapper<Attachment>) wrapper;
                queryWrapper.getSqlSegment();
                assertThat(queryWrapper.getParamNameValuePairs()).containsValue("Product");
            });
    }

    @Test
    void frozenBomQueryAcceptsFrozenFlagOrReleasedStatus() {
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProcessRepository processRepository = mock(ProcessRepository.class);
        AttachmentRepository attachmentRepository = mock(AttachmentRepository.class);
        ProductReleaseGateValidatorImpl validator = new ProductReleaseGateValidatorImpl(
            bomRepository,
            processRepository,
            attachmentRepository,
            new TimelineDefinitionProvider()
        );
        when(bomRepository.selectCount(Mockito.<Wrapper<ProductBom>>any())).thenReturn(1L);
        when(processRepository.selectCount(Mockito.<Wrapper<ProcessEntity>>any())).thenReturn(1L);
        when(attachmentRepository.selectCount(Mockito.<Wrapper<Attachment>>any()))
            .thenReturn(1L, 1L, 0L, 1L);

        validator.check(releasableProduct());

        ArgumentCaptor<Wrapper<ProductBom>> wrapperCaptor = ArgumentCaptor.forClass(Wrapper.class);
        verify(bomRepository).selectCount(wrapperCaptor.capture());
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(new MybatisConfiguration(), "test"), ProductBom.class);
        LambdaQueryWrapper<ProductBom> queryWrapper = (LambdaQueryWrapper<ProductBom>) wrapperCaptor.getValue();
        assertThat(queryWrapper.getSqlSegment())
            .contains("frozen_flag")
            .contains("status");
        assertThat(queryWrapper.getParamNameValuePairs()).containsValue("released");
    }

    @Test
    void checkPassesForModelVariantFinalMoldTransferNode() {
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProcessRepository processRepository = mock(ProcessRepository.class);
        AttachmentRepository attachmentRepository = mock(AttachmentRepository.class);
        ProductReleaseGateValidatorImpl validator = new ProductReleaseGateValidatorImpl(
            bomRepository,
            processRepository,
            attachmentRepository,
            new TimelineDefinitionProvider()
        );
        Product product = releasableProduct();
        product.setProductType("model_variant");
        product.setCurrentStepNo(18);
        product.setTimelineConfirmedNodeKey("MODEL_VARIANT_MOLD_TRANSFER");
        when(bomRepository.selectCount(Mockito.<Wrapper<ProductBom>>any())).thenReturn(1L);
        when(processRepository.selectCount(Mockito.<Wrapper<ProcessEntity>>any())).thenReturn(1L);
        when(attachmentRepository.selectCount(Mockito.<Wrapper<Attachment>>any()))
            .thenReturn(1L, 0L, 1L, 1L);

        var result = validator.check(product);

        assertThat(result.getPassed()).isTrue();
        assertThat(result.getCurrentNodeKey()).isEqualTo("MODEL_VARIANT_MOLD_TRANSFER");
        assertThat(result.getMissingItems()).isEmpty();
    }

    @Test
    void checkRejectsModelVariantBeforeFinalNodeForFormalRelease() {
        ProductBomRepository bomRepository = mock(ProductBomRepository.class);
        ProcessRepository processRepository = mock(ProcessRepository.class);
        AttachmentRepository attachmentRepository = mock(AttachmentRepository.class);
        ProductReleaseGateValidatorImpl validator = new ProductReleaseGateValidatorImpl(
            bomRepository,
            processRepository,
            attachmentRepository,
            new TimelineDefinitionProvider()
        );
        Product product = releasableProduct();
        product.setProductType("model_variant");
        product.setCurrentStepNo(17);
        product.setTimelineConfirmedNodeKey("MODEL_VARIANT_SMALL_BATCH_TEST");
        when(bomRepository.selectCount(Mockito.<Wrapper<ProductBom>>any())).thenReturn(1L);
        when(processRepository.selectCount(Mockito.<Wrapper<ProcessEntity>>any())).thenReturn(1L);
        when(attachmentRepository.selectCount(Mockito.<Wrapper<Attachment>>any()))
            .thenReturn(1L, 1L, 0L, 1L);

        var result = validator.check(product);

        assertThat(result.getPassed()).isFalse();
        assertThat(result.getMissingItems())
            .extracting("code")
            .contains("TIMELINE_NODE_NOT_ALLOWED");
    }

    private Product releasableProduct() {
        Product product = new Product();
        product.setProductId(10L);
        product.setProductType("product_line");
        product.setStatus("released");
        product.setCurrentStepNo(22);
        product.setTimelineCurrentConfirmed(true);
        product.setTimelineConfirmedNodeKey("PRODUCT_LINE_PRODUCTION_DECISION_STEP");
        product.setDeletedFlag(0);
        return product;
    }
}
