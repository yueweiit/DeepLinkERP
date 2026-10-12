package com.yuewei.plm.module.project.service.impl;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.constant.ProductStatusConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.common.security.CurrentUserContext;
import com.yuewei.plm.module.attachment.entity.Attachment;
import com.yuewei.plm.module.attachment.repository.AttachmentRepository;
import com.yuewei.plm.module.operationlog.constant.OperationActionConstants;
import com.yuewei.plm.module.bom.service.ProductionConfirmationService;
import com.yuewei.plm.module.operationlog.service.OperationLogCreateCommand;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.integration.dingtalk.service.DingTalkProjectCompletionReturnService;
import com.yuewei.plm.module.project.constant.TimelineNodeConstants;
import com.yuewei.plm.module.project.dto.TimelineActionDTO;
import com.yuewei.plm.module.project.service.TimelineDefinitionProvider;
import com.yuewei.plm.module.project.variant.entity.RequirementForm;
import com.yuewei.plm.module.project.variant.repository.RequirementFormRepository;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import jakarta.servlet.http.HttpServletRequest;
import java.util.List;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

class TimelineActionServiceImplTest {

    private ProductRepository productRepository;
    private AttachmentRepository attachmentRepository;
    private OperationLogService operationLogService;
    private ProductionConfirmationService productionConfirmationService;
    private RequirementFormRepository requirementFormRepository;
    private TimelineActionServiceImpl service;
    private HttpServletRequest request;

    @BeforeEach
    void setUp() {
        productRepository = mock(ProductRepository.class);
        attachmentRepository = mock(AttachmentRepository.class);
        operationLogService = mock(OperationLogService.class);
        productionConfirmationService = mock(ProductionConfirmationService.class);
        requirementFormRepository = mock(RequirementFormRepository.class);
        RequirementForm confirmedForm = new RequirementForm();
        confirmedForm.setStatus("confirmed");
        confirmedForm.setDeletedFlag(0);
        when(requirementFormRepository.selectList(Mockito.<Wrapper<RequirementForm>>any())).thenReturn(List.of(confirmedForm));
        service = new TimelineActionServiceImpl(
            productRepository,
            attachmentRepository,
            new TimelineDefinitionProvider(),
            operationLogService,
            productionConfirmationService,
            requirementFormRepository
        );
        request = mock(HttpServletRequest.class);
        when(attachmentRepository.selectCount(anyWrapper())).thenReturn(1L);
        CurrentUserContext.set(new CurrentUser(1L, "engineer01", "Engineer One", true));
    }

    @Test
    void confirmProcessPlanRequiresDeterminedBomRoutes() {
        Product product = product(108L, 9);
        when(productRepository.selectById(108L)).thenReturn(product);
        when(operationLogService.logSuccess(any(OperationLogCreateCommand.class))).thenReturn(508L);

        service.confirm(108L, "PRODUCT_LINE_PROCESS_PLAN", new TimelineActionDTO(), request);

        verify(productionConfirmationService).requireBomRoutesDetermined(108L);
    }

    @Test
    void confirmProcessStepRequiresProductionOperations() {
        Product product = product(109L, 10);
        when(productRepository.selectById(109L)).thenReturn(product);
        when(operationLogService.logSuccess(any(OperationLogCreateCommand.class))).thenReturn(509L);

        service.confirm(109L, "PRODUCT_LINE_PROCESS_CONFIRM", new TimelineActionDTO(), request);

        verify(productionConfirmationService).requireOperationsConfirmed(109L);
    }

    @Test
    void confirmProductionDecisionRequiresColors() {
        Product product = product(110L, 22);
        when(productRepository.selectById(110L)).thenReturn(product);
        when(operationLogService.logSuccess(any(OperationLogCreateCommand.class))).thenReturn(510L);

        service.confirm(110L, "PRODUCT_LINE_PRODUCTION_DECISION_STEP", new TimelineActionDTO(), request);

        verify(productionConfirmationService).requireColorsConfirmed(110L);
    }

    @Test
    void confirmProductLineFinalStepReleasesProjectAndTriggersDingTalkCc() {
        Product product = product(115L, 22);
        DingTalkProjectCompletionReturnService completionReturnService = mock(DingTalkProjectCompletionReturnService.class);
        ReflectionTestUtils.setField(service, "dingTalkProjectCompletionReturnService", completionReturnService);
        when(productRepository.selectById(115L)).thenReturn(product);
        when(operationLogService.logSuccess(any(OperationLogCreateCommand.class))).thenReturn(515L);

        var result = service.confirm(
            115L,
            "PRODUCT_LINE_PRODUCTION_DECISION_STEP",
            TimelineActionDTO.builder().remark("product line completed").build(),
            request
        );

        assertThat(result.getCurrentStepNo()).isEqualTo(22);
        assertThat(result.getCurrentConfirmed()).isTrue();
        assertThat(result.getProductStatus()).isEqualTo(ProductStatusConstants.RELEASED);
        assertThat(product.getReleasedAt()).isNotNull();
        assertThat(product.getReleasedBy()).isEqualTo("Engineer One");
        verify(completionReturnService).handleProjectCompleted(
            product,
            TimelineNodeConstants.PRODUCT_LINE_NODES.get(21),
            "Engineer One"
        );
    }

    @Test
    void confirmMoldTransferWithoutTrackingMovesLikeNormalStep() {
        Product product = product(112L, 18);
        when(productRepository.selectById(112L)).thenReturn(product);
        when(operationLogService.logSuccess(any(OperationLogCreateCommand.class))).thenReturn(512L);

        var result = service.confirm(
            112L,
            "PRODUCT_LINE_MOLD_TRANSFER",
            TimelineActionDTO.builder().remark("normal progress").build(),
            request
        );

        assertThat(result.getCurrentStepNo()).isEqualTo(19);
        assertThat(result.getCurrentNodeKey()).isEqualTo("PRODUCT_LINE_MX_ACCEPTANCE");
        assertThat(result.getCurrentConfirmed()).isFalse();
        verify(productRepository).updateById(product);
    }

    @Test
    void confirmModelVariantMoldTransferCompletesPlmProject() {
        Product product = product(113L, 18);
        product.setProductType(TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT);
        DingTalkProjectCompletionReturnService completionReturnService = mock(DingTalkProjectCompletionReturnService.class);
        ReflectionTestUtils.setField(service, "dingTalkProjectCompletionReturnService", completionReturnService);
        when(productRepository.selectById(113L)).thenReturn(product);
        when(operationLogService.logSuccess(any(OperationLogCreateCommand.class))).thenReturn(513L);

        var result = service.confirm(
            113L,
            "MODEL_VARIANT_MOLD_TRANSFER",
            TimelineActionDTO.builder().remark("handover to DingTalk").build(),
            request
        );

        assertThat(result.getCurrentStepNo()).isEqualTo(18);
        assertThat(result.getCurrentNodeKey()).isEqualTo("MODEL_VARIANT_MOLD_TRANSFER");
        assertThat(result.getCurrentConfirmed()).isTrue();
        assertThat(result.getProductStatus()).isEqualTo(ProductStatusConstants.RELEASED);
        assertThat(product.getStatus()).isEqualTo(ProductStatusConstants.RELEASED);
        assertThat(product.getReleasedAt()).isNotNull();
        assertThat(product.getReleasedBy()).isEqualTo("Engineer One");
        verify(productRepository).updateById(product);
        verify(productionConfirmationService).requireColorsConfirmed(113L);
        verify(productionConfirmationService).syncModelVariantConfirmedColorsAndSkus(product);
        verify(completionReturnService).handleProjectCompleted(
            product,
            TimelineNodeConstants.MODEL_VARIANT_NODES.get(17),
            "Engineer One"
        );
    }

    @Test
    void confirmModelVariantMoldTransferStillCompletesWhenDingTalkReturnFails() {
        Product product = product(116L, 18);
        product.setProductType(TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT);
        DingTalkProjectCompletionReturnService completionReturnService = mock(DingTalkProjectCompletionReturnService.class);
        ReflectionTestUtils.setField(service, "dingTalkProjectCompletionReturnService", completionReturnService);
        when(productRepository.selectById(116L)).thenReturn(product);
        when(operationLogService.logSuccess(any(OperationLogCreateCommand.class))).thenReturn(516L);
        doThrow(new IllegalStateException("external_status must not be null"))
            .when(completionReturnService)
            .handleProjectCompleted(any(Product.class), any(TimelineNodeConstants.TimelineNodeDefinition.class), any(String.class));

        var result = service.confirm(
            116L,
            "MODEL_VARIANT_MOLD_TRANSFER",
            TimelineActionDTO.builder().remark("handover to DingTalk").build(),
            request
        );

        assertThat(result.getCurrentStepNo()).isEqualTo(18);
        assertThat(result.getCurrentConfirmed()).isTrue();
        assertThat(result.getProductStatus()).isEqualTo(ProductStatusConstants.RELEASED);
        assertThat(product.getStatus()).isEqualTo(ProductStatusConstants.RELEASED);
        verify(productRepository).updateById(product);
        verify(productionConfirmationService).requireColorsConfirmed(116L);
        verify(productionConfirmationService).syncModelVariantConfirmedColorsAndSkus(product);
    }

    @AfterEach
    void tearDown() {
        CurrentUserContext.clear();
    }

    @Test
    void confirmCurrentSmallStepMovesToNextSmallStepAndWritesLog() {
        Product product = product(100L, 1);
        when(productRepository.selectById(100L)).thenReturn(product);
        when(operationLogService.logSuccess(any(OperationLogCreateCommand.class))).thenReturn(501L);

        var result = service.confirm(
            100L,
            "PRODUCT_LINE_INIT_CREATE",
            TimelineActionDTO.builder().remark("init docs ready").build(),
            request
        );

        assertThat(result.getAction()).isEqualTo("confirm");
        assertThat(result.getBeforeStepNo()).isEqualTo(1);
        assertThat(result.getCurrentStepNo()).isEqualTo(2);
        assertThat(result.getCurrentNodeKey()).isEqualTo("PRODUCT_LINE_INIT_APPROVE");
        assertThat(result.getCurrentConfirmed()).isFalse();
        assertThat(result.getLogId()).isEqualTo(501L);
        assertThat(product.getCurrentStepNo()).isEqualTo(2);
        assertThat(product.getTimelineCurrentConfirmed()).isFalse();
        assertThat(product.getTimelineConfirmedNodeKey()).isNull();
        assertThat(product.getTimelineLastAction()).isEqualTo("confirm");
        assertThat(product.getTimelineLastReason()).isEqualTo("init docs ready");
        verify(productRepository).updateById(product);
        verify(operationLogService).logSuccess(argThat(command ->
            OperationActionConstants.TIMELINE_CONFIRM.equals(command.getAction())
                && "PRODUCT".equals(command.getBusinessType())
                && "100".equals(command.getBusinessId())
                && command.getDetailJson().contains("\"fromNodeKey\":\"PRODUCT_LINE_INIT_CREATE\"")
                && command.getDetailJson().contains("\"toNodeKey\":\"PRODUCT_LINE_INIT_APPROVE\"")
        ));
    }

    @Test
    void confirmLastStepOfStageWithoutRequiredDocumentMovesAndReturnsWarning() {
        Product product = product(101L, 2);
        when(productRepository.selectById(101L)).thenReturn(product);
        when(attachmentRepository.selectList(anyWrapper())).thenReturn(List.of());

        var result = service.confirm(
            101L,
            "PRODUCT_LINE_INIT_APPROVE",
            TimelineActionDTO.builder().remark("go design").build(),
            request
        );

        assertThat(result.getWarnings()).contains("当前阶段资料未齐全：PRODUCT_LINE_INIT_CREATE");
        verify(productRepository).updateById(product);
        verify(operationLogService).logSuccess(argThat(command ->
            command.getDetailJson().contains("\"documentWarnings\"")
                && command.getDetailJson().contains("PRODUCT_LINE_INIT_CREATE")
        ));
    }

    @Test
    void modelVariantTimelineActionsAreBlockedBeforeRequirementFormConfirmation() {
        Product product = product(117L, 1);
        product.setProductType(TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT);
        RequirementForm draft = new RequirementForm();
        draft.setProjectId(117L);
        draft.setStatus("draft");
        draft.setDeletedFlag(0);
        when(productRepository.selectById(117L)).thenReturn(product);
        when(requirementFormRepository.selectList(Mockito.<Wrapper<RequirementForm>>any())).thenReturn(List.of(draft));

        assertThatThrownBy(() -> service.confirm(
            117L,
            "MODEL_VARIANT_INIT_CREATE",
            TimelineActionDTO.builder().remark("绕过完善表").build(),
            request
        ))
            .isInstanceOf(BusinessException.class)
            .hasMessageContaining("请先完成新型号项目信息完善表");

        verify(productRepository, never()).updateById(any(Product.class));
        verify(operationLogService, never()).logSuccess(any(OperationLogCreateCommand.class));
    }

    @Test
    void confirmCurrentRequiredStepWithoutAttachmentMovesAndReturnsWarning() {
        Product product = product(111L, 3);
        when(productRepository.selectById(111L)).thenReturn(product);
        when(attachmentRepository.selectCount(anyWrapper())).thenReturn(0L);

        var result = service.confirm(
            111L,
            "PRODUCT_LINE_DESIGN_DRAWING",
            TimelineActionDTO.builder().remark("drawing checked").build(),
            request
        );

        assertThat(result.getWarnings()).contains("当前步骤资料未上传：画图查看");
        verify(productRepository).updateById(product);
    }

    @Test
    void confirmLastStepOfStageWithRequiredDocumentMovesToNextStage() {
        Product product = product(102L, 2);
        when(productRepository.selectById(102L)).thenReturn(product);
        when(attachmentRepository.selectList(anyWrapper())).thenReturn(List.of(attachment("PRODUCT_LINE_INIT_CREATE", "other")));
        when(operationLogService.logSuccess(any(OperationLogCreateCommand.class))).thenReturn(502L);

        var result = service.confirm(
            102L,
            "PRODUCT_LINE_INIT_APPROVE",
            TimelineActionDTO.builder().remark("go design").build(),
            request
        );

        assertThat(result.getCurrentStepNo()).isEqualTo(3);
        assertThat(result.getCurrentNodeKey()).isEqualTo("PRODUCT_LINE_DESIGN_DRAWING");
        assertThat(result.getCurrentConfirmed()).isFalse();
        assertThat(product.getStatus()).isEqualTo(ProductStatusConstants.DEVELOPING);
        verify(productRepository).updateById(product);
    }

    @Test
    void confirmLastStepOfStageWithRequiredDocumentIgnoresAttachmentCategory() {
        Product product = product(107L, 2);
        when(productRepository.selectById(107L)).thenReturn(product);
        when(attachmentRepository.selectList(anyWrapper())).thenReturn(List.of(attachment("PRODUCT_LINE_INIT_CREATE", "testing")));
        when(operationLogService.logSuccess(any(OperationLogCreateCommand.class))).thenReturn(504L);

        var result = service.confirm(
            107L,
            "PRODUCT_LINE_INIT_APPROVE",
            TimelineActionDTO.builder().remark("go design with uploaded file").build(),
            request
        );

        assertThat(result.getCurrentStepNo()).isEqualTo(3);
        assertThat(result.getCurrentNodeKey()).isEqualTo("PRODUCT_LINE_DESIGN_DRAWING");
        assertThat(result.getCurrentConfirmed()).isFalse();
        verify(productRepository).updateById(product);
    }

    @Test
    void confirmNonCurrentStepThrowsAndDoesNotWriteLog() {
        Product product = product(103L, 2);
        when(productRepository.selectById(103L)).thenReturn(product);

        assertThatThrownBy(() -> service.confirm(
            103L,
            "PRODUCT_LINE_DESIGN_DRAWING",
            TimelineActionDTO.builder().remark("wrong").build(),
            request
        ))
            .isInstanceOf(BusinessException.class)
            .extracting("code")
            .isEqualTo(ErrorCodeConstants.STATUS_TRANSITION_ILLEGAL);

        verify(productRepository, never()).updateById(any(Product.class));
        verify(operationLogService, never()).logSuccess(any(OperationLogCreateCommand.class));
    }

    @Test
    void returnToPreviousStepRecordsReasonAndWritesLog() {
        Product product = product(106L, 3);
        product.setTimelineCurrentConfirmed(true);
        product.setTimelineConfirmedNodeKey("PRODUCT_LINE_DESIGN_DRAWING");
        when(productRepository.selectById(106L)).thenReturn(product);
        when(operationLogService.logSuccess(any(OperationLogCreateCommand.class))).thenReturn(503L);

        var result = service.returnNode(
            106L,
            "PRODUCT_LINE_DESIGN_DRAWING",
            TimelineActionDTO.builder()
                .reason("drawing needs rework")
                .returnToPrevious(true)
                .build(),
            request
        );

        assertThat(result.getAction()).isEqualTo("return");
        assertThat(result.getBeforeStepNo()).isEqualTo(3);
        assertThat(result.getCurrentStepNo()).isEqualTo(2);
        assertThat(result.getCurrentNodeKey()).isEqualTo("PRODUCT_LINE_INIT_APPROVE");
        assertThat(result.getCurrentConfirmed()).isFalse();
        assertThat(product.getCurrentStepNo()).isEqualTo(2);
        assertThat(product.getTimelineCurrentConfirmed()).isFalse();
        assertThat(product.getTimelineConfirmedNodeKey()).isNull();
        assertThat(product.getTimelineLastAction()).isEqualTo("return");
        assertThat(product.getTimelineLastReason()).isEqualTo("drawing needs rework");
        verify(productRepository).updateById(product);
        verify(operationLogService).logSuccess(argThat(command ->
            OperationActionConstants.TIMELINE_RETURN.equals(command.getAction())
                && command.getDetailJson().contains("\"reason\":\"drawing needs rework\"")
                && command.getDetailJson().contains("\"toStepNo\":2")
        ));
    }

    @SuppressWarnings("unchecked")
    private Wrapper<Attachment> anyWrapper() {
        return any(Wrapper.class);
    }

    private Attachment attachment(String nodeKey, String category) {
        Attachment attachment = new Attachment();
        attachment.setTimelineNodeKey(nodeKey);
        attachment.setFileCategory(category);
        attachment.setDeletedFlag(0);
        return attachment;
    }

    private Product product(Long productId, Integer currentStepNo) {
        Product product = new Product();
        product.setProductId(productId);
        product.setProductCode("PRD-CD30-0001");
        product.setProductName("Super Captain 3.0");
        product.setProductType(TimelineNodeConstants.PRODUCT_TYPE_PRODUCT_LINE);
        product.setStatus(ProductStatusConstants.DEVELOPING);
        product.setCurrentStepNo(currentStepNo);
        product.setDeletedFlag(0);
        return product;
    }
}
