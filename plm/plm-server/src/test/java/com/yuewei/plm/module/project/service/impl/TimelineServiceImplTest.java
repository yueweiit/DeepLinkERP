package com.yuewei.plm.module.project.service.impl;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.yuewei.plm.common.constant.ProductStatusConstants;
import com.yuewei.plm.module.attachment.entity.Attachment;
import com.yuewei.plm.module.attachment.repository.AttachmentRepository;
import com.yuewei.plm.module.project.constant.TimelineNodeConstants;
import com.yuewei.plm.module.project.service.MoldTransferExpressService;
import com.yuewei.plm.module.project.service.TimelineDefinitionProvider;
import com.yuewei.plm.module.project.variant.entity.RequirementForm;
import com.yuewei.plm.module.project.variant.repository.RequirementFormRepository;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import org.junit.jupiter.api.Test;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;
import java.util.List;

class TimelineServiceImplTest {

    @Test
    void buildsProductLineTimelineWithSingleCurrentNode() {
        ProductRepository productRepository = mock(ProductRepository.class);
        AttachmentRepository attachmentRepository = mock(AttachmentRepository.class);
        when(attachmentRepository.selectCount(Mockito.<Wrapper<Attachment>>any())).thenReturn(0L);
        TimelineServiceImpl service = new TimelineServiceImpl(
            productRepository,
            new TimelineDefinitionProvider(),
            attachmentRepository,
            mock(MoldTransferExpressService.class),
            mock(RequirementFormRepository.class)
        );
        Product product = product(10L, TimelineNodeConstants.PRODUCT_TYPE_PRODUCT_LINE, 2);
        product.setTimelineCurrentConfirmed(true);
        product.setTimelineConfirmedNodeKey("PRODUCT_LINE_INIT_APPROVE");
        product.setTimelineLastAction("confirm");
        product.setTimelineLastReason("design checked");
        product.setTimelineLastOperatorUserId(1L);
        product.setTimelineLastOperatorUserName("Engineer One");
        when(productRepository.selectById(10L)).thenReturn(product);

        var timeline = service.getTimeline(10L);

        assertThat(timeline.getProjectId()).isEqualTo(10L);
        assertThat(timeline.getProductId()).isEqualTo(10L);
        assertThat(timeline.getProductType()).isEqualTo(TimelineNodeConstants.PRODUCT_TYPE_PRODUCT_LINE);
        assertThat(timeline.getCurrentStepNo()).isEqualTo(2);
        assertThat(timeline.getCurrentStageCode()).isEqualTo("PRODUCT_LINE_INIT_CONFIRM");
        assertThat(timeline.getCurrentStepCode()).isEqualTo("PRODUCT_LINE_INIT_APPROVE");
        assertThat(timeline.getNodes()).hasSize(22);
        assertThat(timeline.getNodes()).extracting("nodeStatus")
            .startsWith("completed", "current", "pending", "pending");
        assertThat(timeline.getNodes()).extracting("documentCount").containsOnly(0);
        assertThat(timeline.getCurrentConfirmed()).isTrue();
        assertThat(timeline.getConfirmedNodeKey()).isEqualTo("PRODUCT_LINE_INIT_APPROVE");
        assertThat(timeline.getLastAction()).isEqualTo("confirm");
        assertThat(timeline.getLastReason()).isEqualTo("design checked");
        assertThat(timeline.getLastOperatorUserId()).isEqualTo(1L);
        assertThat(timeline.getLastOperatorUserName()).isEqualTo("Engineer One");
        assertThat(timeline.getNodes()).extracting("confirmed")
            .startsWith(false, true, false, false);
        assertThat(timeline.getNodes().get(0).getStageCode()).isEqualTo("PRODUCT_LINE_INIT_CONFIRM");
        assertThat(timeline.getNodes().get(0).getPhaseName()).isNotBlank();
        assertThat(timeline.getNodes().get(0).getRequiredFileCategory()).isEqualTo("other");
        ArgumentCaptor<Wrapper<Attachment>> wrapperCaptor = ArgumentCaptor.forClass(Wrapper.class);
        verify(attachmentRepository, times(22)).selectCount(wrapperCaptor.capture());
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(new MybatisConfiguration(), "test"), Attachment.class);
        assertThat(wrapperCaptor.getAllValues())
            .allSatisfy(wrapper -> {
                LambdaQueryWrapper<Attachment> queryWrapper = (LambdaQueryWrapper<Attachment>) wrapper;
                queryWrapper.getSqlSegment();
                assertThat(queryWrapper.getParamNameValuePairs()).containsValue("Product");
            });
    }

    @Test
    void clampsCurrentStepNoAboveDefinitionSize() {
        ProductRepository productRepository = mock(ProductRepository.class);
        AttachmentRepository attachmentRepository = mock(AttachmentRepository.class);
        when(attachmentRepository.selectCount(Mockito.<Wrapper<Attachment>>any())).thenReturn(0L);
        RequirementFormRepository requirementFormRepository = mock(RequirementFormRepository.class);
        RequirementForm form = new RequirementForm();
        form.setProjectId(11L);
        form.setStatus("confirmed");
        form.setDeletedFlag(0);
        when(requirementFormRepository.selectList(Mockito.any())).thenReturn(List.of(form));
        TimelineServiceImpl service = new TimelineServiceImpl(
            productRepository,
            new TimelineDefinitionProvider(),
            attachmentRepository,
            mock(MoldTransferExpressService.class),
            requirementFormRepository
        );
        Product product = product(11L, TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT, 99);
        when(productRepository.selectById(11L)).thenReturn(product);

        var timeline = service.getTimeline(11L);

        assertThat(timeline.getCurrentStepNo()).isEqualTo(18);
        assertThat(timeline.getCurrentStepCode()).isEqualTo("MODEL_VARIANT_MOLD_TRANSFER");
        assertThat(timeline.getNodes()).extracting("nodeStatus")
            .startsWith("completed", "completed", "completed", "completed", "completed")
            .endsWith("current");
    }

    @Test
    void releasedModelVariantFinalStepShowsCompletedTimeline() {
        ProductRepository productRepository = mock(ProductRepository.class);
        AttachmentRepository attachmentRepository = mock(AttachmentRepository.class);
        when(attachmentRepository.selectCount(Mockito.<Wrapper<Attachment>>any())).thenReturn(0L);
        RequirementFormRepository requirementFormRepository = mock(RequirementFormRepository.class);
        RequirementForm form = new RequirementForm();
        form.setProjectId(14L);
        form.setStatus("confirmed");
        form.setDeletedFlag(0);
        when(requirementFormRepository.selectList(Mockito.any())).thenReturn(List.of(form));
        TimelineServiceImpl service = new TimelineServiceImpl(
            productRepository,
            new TimelineDefinitionProvider(),
            attachmentRepository,
            mock(MoldTransferExpressService.class),
            requirementFormRepository
        );
        Product product = product(14L, TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT, 18);
        product.setStatus(ProductStatusConstants.RELEASED);
        product.setTimelineCurrentConfirmed(true);
        product.setTimelineConfirmedNodeKey("MODEL_VARIANT_MOLD_TRANSFER");
        when(productRepository.selectById(14L)).thenReturn(product);

        var timeline = service.getTimeline(14L);

        assertThat(timeline.getTimelineCompleted()).isTrue();
        assertThat(timeline.getCurrentConfirmed()).isTrue();
        assertThat(timeline.getCurrentStepName()).isEqualTo("运模");
        assertThat(timeline.getCurrentStepCode()).isEqualTo("MODEL_VARIANT_MOLD_TRANSFER");
        assertThat(timeline.getNodes()).extracting("nodeStatus").containsOnly("completed");
    }

    @Test
    void releasedProductLineFinalStepShowsCompletedTimeline() {
        ProductRepository productRepository = mock(ProductRepository.class);
        AttachmentRepository attachmentRepository = mock(AttachmentRepository.class);
        when(attachmentRepository.selectCount(Mockito.<Wrapper<Attachment>>any())).thenReturn(0L);
        TimelineServiceImpl service = new TimelineServiceImpl(
            productRepository,
            new TimelineDefinitionProvider(),
            attachmentRepository,
            mock(MoldTransferExpressService.class),
            mock(RequirementFormRepository.class)
        );
        Product product = product(15L, TimelineNodeConstants.PRODUCT_TYPE_PRODUCT_LINE, 22);
        product.setStatus(ProductStatusConstants.RELEASED);
        product.setTimelineCurrentConfirmed(true);
        product.setTimelineConfirmedNodeKey("PRODUCT_LINE_PRODUCTION_DECISION_STEP");
        when(productRepository.selectById(15L)).thenReturn(product);

        var timeline = service.getTimeline(15L);

        assertThat(timeline.getTimelineCompleted()).isTrue();
        assertThat(timeline.getCurrentConfirmed()).isTrue();
        assertThat(timeline.getCurrentStepName()).isEqualTo("投产决策");
        assertThat(timeline.getCurrentStepCode()).isEqualTo("PRODUCT_LINE_PRODUCTION_DECISION_STEP");
        assertThat(timeline.getNodes()).extracting("nodeStatus").containsOnly("completed");
    }

    @Test
    void archivedModelVariantTimelineShowsCompleted() {
        ProductRepository productRepository = mock(ProductRepository.class);
        AttachmentRepository attachmentRepository = mock(AttachmentRepository.class);
        when(attachmentRepository.selectCount(Mockito.<Wrapper<Attachment>>any())).thenReturn(0L);
        RequirementFormRepository requirementFormRepository = mock(RequirementFormRepository.class);
        RequirementForm form = new RequirementForm();
        form.setProjectId(12L);
        form.setStatus("confirmed");
        form.setDeletedFlag(0);
        when(requirementFormRepository.selectList(Mockito.any())).thenReturn(List.of(form));
        TimelineServiceImpl service = new TimelineServiceImpl(
            productRepository,
            new TimelineDefinitionProvider(),
            attachmentRepository,
            mock(MoldTransferExpressService.class),
            requirementFormRepository
        );
        Product product = product(12L, TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT, 18);
        product.setStatus(ProductStatusConstants.ARCHIVED);
        product.setTimelineCurrentConfirmed(true);
        product.setTimelineConfirmedNodeKey("MODEL_VARIANT_MOLD_TRANSFER");
        when(productRepository.selectById(12L)).thenReturn(product);

        var timeline = service.getTimeline(12L);

        assertThat(timeline.getCurrentStepName()).isEqualTo("已完结");
        assertThat(timeline.getNodes()).extracting("nodeStatus").containsOnly("completed");
        assertThat(timeline.getCurrentConfirmed()).isTrue();
    }

    @Test
    void modelVariantTimelineIsHiddenUntilRequirementFormIsConfirmed() {
        ProductRepository productRepository = mock(ProductRepository.class);
        AttachmentRepository attachmentRepository = mock(AttachmentRepository.class);
        RequirementFormRepository requirementFormRepository = mock(RequirementFormRepository.class);
        RequirementForm form = new RequirementForm();
        form.setProjectId(13L);
        form.setStatus("draft");
        form.setDeletedFlag(0);
        when(productRepository.selectById(13L)).thenReturn(product(13L, TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT, 1));
        when(requirementFormRepository.selectList(Mockito.any())).thenReturn(List.of(form));

        TimelineServiceImpl service = new TimelineServiceImpl(
            productRepository,
            new TimelineDefinitionProvider(),
            attachmentRepository,
            mock(MoldTransferExpressService.class),
            requirementFormRepository
        );

        var timeline = service.getTimeline(13L);

        assertThat(timeline.getStarted()).isFalse();
        assertThat(timeline.getStartBlockReason()).contains("请先完成新型号项目信息完善表");
        assertThat(timeline.getCurrentStepNo()).isEqualTo(1);
        assertThat(timeline.getNodes()).isEmpty();
    }

    @Test
    void missingProductThrowsNotFound() {
        ProductRepository productRepository = mock(ProductRepository.class);
        TimelineServiceImpl service = new TimelineServiceImpl(
            productRepository,
            new TimelineDefinitionProvider(),
            mock(AttachmentRepository.class),
            mock(MoldTransferExpressService.class),
            mock(RequirementFormRepository.class)
        );
        when(productRepository.selectById(999L)).thenReturn(null);

        assertThatThrownBy(() -> service.getTimeline(999L))
            .isInstanceOf(BusinessException.class)
            .extracting("code")
            .isEqualTo(ErrorCodeConstants.RESOURCE_NOT_FOUND);
    }

    private Product product(Long productId, String productType, Integer currentStepNo) {
        Product product = new Product();
        product.setProductId(productId);
        product.setProductType(productType);
        product.setCurrentStepNo(currentStepNo);
        product.setDeletedFlag(0);
        return product;
    }
}
