package com.yuewei.plm.module.integration.dingtalk;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.module.integration.dingtalk.config.DingTalkIntegrationProperties;
import com.yuewei.plm.module.integration.dingtalk.entity.IntegrationRecord;
import com.yuewei.plm.module.integration.dingtalk.repository.IntegrationRecordRepository;
import com.yuewei.plm.module.integration.dingtalk.service.DingTalkOutboundApprovalClient;
import com.yuewei.plm.module.integration.dingtalk.service.DingTalkOutboundApprovalClient.DingTalkOutboundResult;
import com.yuewei.plm.module.integration.dingtalk.service.DingTalkProjectCompletionReturnService;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.project.constant.TimelineNodeConstants;
import com.yuewei.plm.module.project.constant.TimelineNodeConstants.TimelineNodeDefinition;
import com.yuewei.plm.repository.entity.Product;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

class DingTalkProjectCompletionReturnServiceTest {

    @Test
    void modelVariantMoldTransferCreatesAutoAgreeOutboundRecord() {
        IntegrationRecordRepository integrationRepository = mock(IntegrationRecordRepository.class);
        DingTalkOutboundApprovalClient outboundClient = mock(DingTalkOutboundApprovalClient.class);
        OperationLogService operationLogService = mock(OperationLogService.class);
        DingTalkIntegrationProperties properties = new DingTalkIntegrationProperties();
        properties.setModelVariantProcessCode("PROC-MODEL");
        properties.setAutoApproverUserId("02356802443226388318");
        when(integrationRepository.selectList(any()))
            .thenReturn(List.of(inbound("model_variant", "ding-instance-001", "{\"taskId\":\"ding-task-001\"}")))
            .thenReturn(List.of());
        when(outboundClient.executeWorkflowTask(any())).thenReturn(new DingTalkOutboundResult(
            "ding-instance-001",
            null,
            "dry_run",
            "{\"status\":\"dry_run\"}"
        ));
        doAnswer(invocation -> {
            IntegrationRecord record = invocation.getArgument(0);
            record.setIntegrationRecordId(501L);
            return 1;
        }).when(integrationRepository).insert(any(IntegrationRecord.class));

        DingTalkProjectCompletionReturnService service = new DingTalkProjectCompletionReturnService(
            integrationRepository,
            outboundClient,
            properties,
            new ObjectMapper(),
            operationLogService
        );

        var result = service.handleProjectCompleted(
            product(113L, TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT),
            new TimelineNodeDefinition(18, "MODEL_VARIANT_MOLD_TRANSFER", "运模"),
            "Engineer One"
        );

        assertThat(result).isNotNull();
        assertThat(result.getStatus()).isEqualTo("success");
        assertThat(result.getIntegrationRecordId()).isEqualTo(501L);
        ArgumentCaptor<Map> payloadCaptor = ArgumentCaptor.forClass(Map.class);
        verify(outboundClient).executeWorkflowTask(payloadCaptor.capture());
        assertThat(payloadCaptor.getValue())
            .containsEntry("action", "agree")
            .containsEntry("processInstanceId", "ding-instance-001")
            .containsEntry("taskId", "ding-task-001")
            .containsEntry("actionerUserId", "02356802443226388318");
        ArgumentCaptor<IntegrationRecord> recordCaptor = ArgumentCaptor.forClass(IntegrationRecord.class);
        verify(integrationRepository).insert(recordCaptor.capture());
        assertThat(recordCaptor.getValue().getIntegrationType()).isEqualTo("model_variant_mold_transfer_completed");
        assertThat(recordCaptor.getValue().getDirection()).isEqualTo("outbound");
        assertThat(recordCaptor.getValue().getExternalInstanceId()).isEqualTo("ding-instance-001");
        assertThat(recordCaptor.getValue().getProcessCode()).isEqualTo("PROC-MODEL");
        assertThat(recordCaptor.getValue().getSourcePayloadJson()).contains("\"action\":\"agree\"");
        assertThat(recordCaptor.getValue().getRetryCount()).isEqualTo(1);
    }

    @Test
    void modelVariantMoldTransferMissingTaskIdSavesFailedOutboundRecordWithExternalStatus() {
        IntegrationRecordRepository integrationRepository = mock(IntegrationRecordRepository.class);
        DingTalkOutboundApprovalClient outboundClient = mock(DingTalkOutboundApprovalClient.class);
        OperationLogService operationLogService = mock(OperationLogService.class);
        DingTalkIntegrationProperties properties = new DingTalkIntegrationProperties();
        properties.setModelVariantProcessCode("PROC-MODEL");
        properties.setAutoApproverUserId("02356802443226388318");
        when(integrationRepository.selectList(any()))
            .thenReturn(List.of(inbound("model_variant", "ding-instance-001", "{}")))
            .thenReturn(List.of());
        doAnswer(invocation -> {
            IntegrationRecord record = invocation.getArgument(0);
            record.setIntegrationRecordId(503L);
            return 1;
        }).when(integrationRepository).insert(any(IntegrationRecord.class));

        DingTalkProjectCompletionReturnService service = new DingTalkProjectCompletionReturnService(
            integrationRepository,
            outboundClient,
            properties,
            new ObjectMapper(),
            operationLogService
        );

        var result = service.handleProjectCompleted(
            product(113L, TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT),
            new TimelineNodeDefinition(18, "MODEL_VARIANT_MOLD_TRANSFER", "Mold transfer"),
            "Engineer One"
        );

        assertThat(result.getStatus()).isEqualTo("failed");
        verify(outboundClient, never()).executeWorkflowTask(any());
        ArgumentCaptor<IntegrationRecord> recordCaptor = ArgumentCaptor.forClass(IntegrationRecord.class);
        verify(integrationRepository).insert(recordCaptor.capture());
        assertThat(recordCaptor.getValue().getExternalStatus()).isEqualTo("failed");
        assertThat(recordCaptor.getValue().getProcessingStatus()).isEqualTo("failed");
        assertThat(recordCaptor.getValue().getErrorCode()).isEqualTo("DINGTALK_PROJECT_COMPLETION_RETURN_FAILED");
        assertThat(recordCaptor.getValue().getErrorMessage()).contains("taskId");
    }

    @Test
    void modelVariantMoldTransferPersistsLookupFailureReasonWhenTaskLookupFails() {
        IntegrationRecordRepository integrationRepository = mock(IntegrationRecordRepository.class);
        DingTalkOutboundApprovalClient outboundClient = mock(DingTalkOutboundApprovalClient.class);
        OperationLogService operationLogService = mock(OperationLogService.class);
        DingTalkIntegrationProperties properties = new DingTalkIntegrationProperties();
        properties.setModelVariantProcessCode("PROC-MODEL");
        properties.setAutoApproverUserId("02356802443226388318");
        when(integrationRepository.selectList(any()))
            .thenReturn(List.of(inbound("model_variant", "ding-instance-001", "{}")))
            .thenReturn(List.of());
        when(outboundClient.lookupWorkflowTask(any()))
            .thenThrow(new RuntimeException("query DingTalk process instance failed: ip not in whitelist"));
        doAnswer(invocation -> {
            IntegrationRecord record = invocation.getArgument(0);
            record.setIntegrationRecordId(506L);
            return 1;
        }).when(integrationRepository).insert(any(IntegrationRecord.class));

        DingTalkProjectCompletionReturnService service = new DingTalkProjectCompletionReturnService(
            integrationRepository,
            outboundClient,
            properties,
            new ObjectMapper(),
            operationLogService
        );

        var result = service.handleProjectCompleted(
            product(113L, TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT),
            new TimelineNodeDefinition(18, "MODEL_VARIANT_MOLD_TRANSFER", "Mold transfer"),
            "Engineer One"
        );

        assertThat(result.getStatus()).isEqualTo("failed");
        ArgumentCaptor<IntegrationRecord> recordCaptor = ArgumentCaptor.forClass(IntegrationRecord.class);
        verify(integrationRepository).insert(recordCaptor.capture());
        assertThat(recordCaptor.getValue().getErrorMessage()).contains("ip not in whitelist");
        assertThat(recordCaptor.getValue().getSourcePayloadJson()).contains("taskLookupError");
    }

    @Test
    void modelVariantMoldTransferLooksUpTaskIdWhenInboundPayloadDoesNotProvideIt() {
        IntegrationRecordRepository integrationRepository = mock(IntegrationRecordRepository.class);
        DingTalkOutboundApprovalClient outboundClient = mock(DingTalkOutboundApprovalClient.class);
        OperationLogService operationLogService = mock(OperationLogService.class);
        DingTalkIntegrationProperties properties = new DingTalkIntegrationProperties();
        properties.setModelVariantProcessCode("PROC-MODEL");
        properties.setAutoApproverUserId("02356802443226388318");
        when(integrationRepository.selectList(any()))
            .thenReturn(List.of(inbound("model_variant", "ding-instance-001", "{}")))
            .thenReturn(List.of());
        when(outboundClient.lookupWorkflowTask(any())).thenReturn("ding-task-looked-up");
        when(outboundClient.executeWorkflowTask(any())).thenReturn(new DingTalkOutboundResult(
            "ding-instance-001",
            null,
            "dry_run",
            "{\"status\":\"dry_run\"}"
        ));
        doAnswer(invocation -> {
            IntegrationRecord record = invocation.getArgument(0);
            record.setIntegrationRecordId(504L);
            return 1;
        }).when(integrationRepository).insert(any(IntegrationRecord.class));

        DingTalkProjectCompletionReturnService service = new DingTalkProjectCompletionReturnService(
            integrationRepository,
            outboundClient,
            properties,
            new ObjectMapper(),
            operationLogService
        );

        var result = service.handleProjectCompleted(
            product(113L, TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT),
            new TimelineNodeDefinition(18, "MODEL_VARIANT_MOLD_TRANSFER", "Mold transfer"),
            "Engineer One"
        );

        assertThat(result.getStatus()).isEqualTo("success");
        ArgumentCaptor<Map> lookupCaptor = ArgumentCaptor.forClass(Map.class);
        verify(outboundClient).lookupWorkflowTask(lookupCaptor.capture());
        assertThat(lookupCaptor.getValue())
            .containsEntry("action", "workflow-task-lookup")
            .containsEntry("processInstanceId", "ding-instance-001")
            .containsEntry("actionerUserId", "02356802443226388318");
        ArgumentCaptor<Map> executeCaptor = ArgumentCaptor.forClass(Map.class);
        verify(outboundClient).executeWorkflowTask(executeCaptor.capture());
        assertThat(executeCaptor.getValue())
            .containsEntry("taskId", "ding-task-looked-up")
            .containsEntry("taskIdSource", "lookup");
    }

    @Test
    void relayBusinessFailureSavesFailedOutboundRecord() {
        IntegrationRecordRepository integrationRepository = mock(IntegrationRecordRepository.class);
        DingTalkOutboundApprovalClient outboundClient = mock(DingTalkOutboundApprovalClient.class);
        OperationLogService operationLogService = mock(OperationLogService.class);
        DingTalkIntegrationProperties properties = new DingTalkIntegrationProperties();
        properties.setModelVariantProcessCode("PROC-MODEL");
        properties.setAutoApproverUserId("02356802443226388318");
        when(integrationRepository.selectList(any()))
            .thenReturn(List.of(inbound("model_variant", "ding-instance-001", "{\"taskId\":\"ding-task-001\"}")))
            .thenReturn(List.of());
        when(outboundClient.executeWorkflowTask(any())).thenReturn(new DingTalkOutboundResult(
            "ding-instance-001",
            null,
            "failed",
            "{\"code\":0,\"data\":{\"status\":\"failed\",\"errorCode\":\"DINGTALK_AGREE_NOT_IMPLEMENTED\"}}"
        ));
        doAnswer(invocation -> {
            IntegrationRecord record = invocation.getArgument(0);
            record.setIntegrationRecordId(505L);
            return 1;
        }).when(integrationRepository).insert(any(IntegrationRecord.class));

        DingTalkProjectCompletionReturnService service = new DingTalkProjectCompletionReturnService(
            integrationRepository,
            outboundClient,
            properties,
            new ObjectMapper(),
            operationLogService
        );

        var result = service.handleProjectCompleted(
            product(113L, TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT),
            new TimelineNodeDefinition(18, "MODEL_VARIANT_MOLD_TRANSFER", "Mold transfer"),
            "Engineer One"
        );

        assertThat(result.getStatus()).isEqualTo("failed");
        ArgumentCaptor<IntegrationRecord> recordCaptor = ArgumentCaptor.forClass(IntegrationRecord.class);
        verify(integrationRepository).insert(recordCaptor.capture());
        assertThat(recordCaptor.getValue().getProcessingStatus()).isEqualTo("failed");
        assertThat(recordCaptor.getValue().getExternalStatus()).isEqualTo("failed");
        assertThat(recordCaptor.getValue().getErrorMessage()).contains("DINGTALK_AGREE_NOT_IMPLEMENTED");
    }

    @Test
    void productLineFinalStepCreatesCcOutboundRecord() {
        IntegrationRecordRepository integrationRepository = mock(IntegrationRecordRepository.class);
        DingTalkOutboundApprovalClient outboundClient = mock(DingTalkOutboundApprovalClient.class);
        OperationLogService operationLogService = mock(OperationLogService.class);
        DingTalkIntegrationProperties properties = new DingTalkIntegrationProperties();
        properties.setProductLineProcessCode("PROC-PRODUCT");
        properties.setProductLineCcUserIds(List.of("02356802443226388318"));
        when(integrationRepository.selectList(any()))
            .thenReturn(List.of(inbound("product_line", "ding-product-001", "{}")))
            .thenReturn(List.of());
        when(outboundClient.sendCompletionNotice(any())).thenReturn(new DingTalkOutboundResult(
            "notice-113",
            null,
            "dry_run",
            "{\"status\":\"dry_run\"}"
        ));
        doAnswer(invocation -> {
            IntegrationRecord record = invocation.getArgument(0);
            record.setIntegrationRecordId(502L);
            return 1;
        }).when(integrationRepository).insert(any(IntegrationRecord.class));

        DingTalkProjectCompletionReturnService service = new DingTalkProjectCompletionReturnService(
            integrationRepository,
            outboundClient,
            properties,
            new ObjectMapper(),
            operationLogService
        );

        var result = service.handleProjectCompleted(
            product(114L, TimelineNodeConstants.PRODUCT_TYPE_PRODUCT_LINE),
            new TimelineNodeDefinition(22, "PRODUCT_LINE_PRODUCTION_DECISION_STEP", "投产决策"),
            "Engineer One"
        );

        assertThat(result).isNotNull();
        assertThat(result.getStatus()).isEqualTo("success");
        ArgumentCaptor<Map> payloadCaptor = ArgumentCaptor.forClass(Map.class);
        verify(outboundClient).sendCompletionNotice(payloadCaptor.capture());
        assertThat(payloadCaptor.getValue())
            .containsEntry("action", "cc")
            .containsEntry("processInstanceId", "ding-product-001");
        assertThat(payloadCaptor.getValue().get("receiverUserIds")).isEqualTo(List.of("02356802443226388318"));
        ArgumentCaptor<IntegrationRecord> recordCaptor = ArgumentCaptor.forClass(IntegrationRecord.class);
        verify(integrationRepository).insert(recordCaptor.capture());
        assertThat(recordCaptor.getValue().getIntegrationType()).isEqualTo("product_line_completed_cc");
        assertThat(recordCaptor.getValue().getSourcePayloadJson()).contains("\"receiverUserIds\":[\"02356802443226388318\"]");
    }

    @Test
    void modelVariantMoldTransferMissingInboundSavesFailedOutboundRecord() {
        IntegrationRecordRepository integrationRepository = mock(IntegrationRecordRepository.class);
        DingTalkOutboundApprovalClient outboundClient = mock(DingTalkOutboundApprovalClient.class);
        OperationLogService operationLogService = mock(OperationLogService.class);
        DingTalkIntegrationProperties properties = new DingTalkIntegrationProperties();
        properties.setModelVariantProcessCode("PROC-MODEL");
        properties.setAutoApproverUserId("02356802443226388318");
        when(integrationRepository.selectList(any()))
            .thenReturn(List.of())
            .thenReturn(List.of());
        doAnswer(invocation -> {
            IntegrationRecord record = invocation.getArgument(0);
            record.setIntegrationRecordId(507L);
            return 1;
        }).when(integrationRepository).insert(any(IntegrationRecord.class));

        DingTalkProjectCompletionReturnService service = new DingTalkProjectCompletionReturnService(
            integrationRepository,
            outboundClient,
            properties,
            new ObjectMapper(),
            operationLogService
        );

        var result = service.handleProjectCompleted(
            product(113L, TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT),
            new TimelineNodeDefinition(18, "MODEL_VARIANT_MOLD_TRANSFER", "运模"),
            "Engineer One"
        );

        assertThat(result).isNotNull();
        assertThat(result.getStatus()).isEqualTo("failed");
        verify(outboundClient, never()).executeWorkflowTask(any());
        ArgumentCaptor<IntegrationRecord> recordCaptor = ArgumentCaptor.forClass(IntegrationRecord.class);
        verify(integrationRepository).insert(recordCaptor.capture());
        assertThat(recordCaptor.getValue().getIntegrationType()).isEqualTo("model_variant_mold_transfer_completed");
        assertThat(recordCaptor.getValue().getExternalInstanceId()).isNull();
        assertThat(recordCaptor.getValue().getProcessingStatus()).isEqualTo("failed");
        assertThat(recordCaptor.getValue().getErrorMessage()).contains("入站记录");
        assertThat(recordCaptor.getValue().getSourcePayloadJson()).contains("missingInboundIntegrationType");
    }

    @Test
    void productLineFinalStepMissingInboundSavesFailedOutboundRecord() {
        IntegrationRecordRepository integrationRepository = mock(IntegrationRecordRepository.class);
        DingTalkOutboundApprovalClient outboundClient = mock(DingTalkOutboundApprovalClient.class);
        OperationLogService operationLogService = mock(OperationLogService.class);
        DingTalkIntegrationProperties properties = new DingTalkIntegrationProperties();
        properties.setProductLineProcessCode("PROC-PRODUCT");
        properties.setProductLineCcUserIds(List.of("02356802443226388318"));
        when(integrationRepository.selectList(any()))
            .thenReturn(List.of())
            .thenReturn(List.of());
        doAnswer(invocation -> {
            IntegrationRecord record = invocation.getArgument(0);
            record.setIntegrationRecordId(508L);
            return 1;
        }).when(integrationRepository).insert(any(IntegrationRecord.class));

        DingTalkProjectCompletionReturnService service = new DingTalkProjectCompletionReturnService(
            integrationRepository,
            outboundClient,
            properties,
            new ObjectMapper(),
            operationLogService
        );

        var result = service.handleProjectCompleted(
            product(114L, TimelineNodeConstants.PRODUCT_TYPE_PRODUCT_LINE),
            new TimelineNodeDefinition(22, "PRODUCT_LINE_PRODUCTION_DECISION_STEP", "投产决策"),
            "Engineer One"
        );

        assertThat(result).isNotNull();
        assertThat(result.getStatus()).isEqualTo("failed");
        verify(outboundClient, never()).sendCompletionNotice(any());
        ArgumentCaptor<IntegrationRecord> recordCaptor = ArgumentCaptor.forClass(IntegrationRecord.class);
        verify(integrationRepository).insert(recordCaptor.capture());
        assertThat(recordCaptor.getValue().getIntegrationType()).isEqualTo("product_line_completed_cc");
        assertThat(recordCaptor.getValue().getProcessingStatus()).isEqualTo("failed");
        assertThat(recordCaptor.getValue().getErrorMessage()).contains("入站记录");
        assertThat(recordCaptor.getValue().getSourcePayloadJson()).contains("missingInboundIntegrationType");
    }

    @Test
    void successfulOutboundRecordIsIdempotent() {
        IntegrationRecordRepository integrationRepository = mock(IntegrationRecordRepository.class);
        DingTalkOutboundApprovalClient outboundClient = mock(DingTalkOutboundApprovalClient.class);
        DingTalkIntegrationProperties properties = new DingTalkIntegrationProperties();
        when(integrationRepository.selectList(any()))
            .thenReturn(List.of(inbound("model_variant", "ding-instance-001", "{}")))
            .thenReturn(List.of(successOutbound()));

        DingTalkProjectCompletionReturnService service = new DingTalkProjectCompletionReturnService(
            integrationRepository,
            outboundClient,
            properties,
            new ObjectMapper(),
            mock(OperationLogService.class)
        );

        var result = service.handleProjectCompleted(
            product(113L, TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT),
            new TimelineNodeDefinition(18, "MODEL_VARIANT_MOLD_TRANSFER", "运模"),
            "Engineer One"
        );

        assertThat(result.isIdempotentHit()).isTrue();
        verify(outboundClient, never()).executeWorkflowTask(any());
        verify(integrationRepository, never()).insert(any(IntegrationRecord.class));
    }

    @Test
    void successfulOutboundRecordWinsEvenWhenFailedRecordIsReturnedFirst() {
        IntegrationRecordRepository integrationRepository = mock(IntegrationRecordRepository.class);
        DingTalkOutboundApprovalClient outboundClient = mock(DingTalkOutboundApprovalClient.class);
        DingTalkIntegrationProperties properties = new DingTalkIntegrationProperties();
        when(integrationRepository.selectList(any()))
            .thenReturn(List.of(inbound("model_variant", "ding-instance-001", "{}")))
            .thenReturn(List.of(failedOutbound(), successOutbound()));

        DingTalkProjectCompletionReturnService service = new DingTalkProjectCompletionReturnService(
            integrationRepository,
            outboundClient,
            properties,
            new ObjectMapper(),
            mock(OperationLogService.class)
        );

        var result = service.handleProjectCompleted(
            product(113L, TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT),
            new TimelineNodeDefinition(18, "MODEL_VARIANT_MOLD_TRANSFER", "运模"),
            "Engineer One"
        );

        assertThat(result.isIdempotentHit()).isTrue();
        assertThat(result.getIntegrationRecordId()).isEqualTo(600L);
        verify(outboundClient, never()).executeWorkflowTask(any());
        verify(integrationRepository, never()).updateById(any(IntegrationRecord.class));
    }

    private IntegrationRecord inbound(String type, String instanceId, String payload) {
        IntegrationRecord record = new IntegrationRecord();
        record.setSourceSystem("dingtalk");
        record.setIntegrationType(type);
        record.setExternalInstanceId(instanceId);
        record.setDirection("inbound");
        record.setSourcePayloadJson(payload);
        record.setProcessingStatus("success");
        record.setDeletedFlag(0);
        return record;
    }

    private IntegrationRecord successOutbound() {
        IntegrationRecord record = new IntegrationRecord();
        record.setIntegrationRecordId(600L);
        record.setSourceSystem("dingtalk");
        record.setIntegrationType("model_variant_mold_transfer_completed");
        record.setProjectId(113L);
        record.setNodeKey("MODEL_VARIANT_MOLD_TRANSFER");
        record.setDirection("outbound");
        record.setExternalInstanceId("ding-instance-001");
        record.setProcessingStatus("success");
        record.setDeletedFlag(0);
        return record;
    }

    private IntegrationRecord failedOutbound() {
        IntegrationRecord record = successOutbound();
        record.setIntegrationRecordId(599L);
        record.setProcessingStatus("failed");
        return record;
    }

    private Product product(Long productId, String productType) {
        Product product = new Product();
        product.setProductId(productId);
        product.setProductCode("PRD-CD30-0001");
        product.setProductName("Super Captain 3.0");
        product.setProductType(productType);
        product.setModel("HR X8D");
        product.setDeletedFlag(0);
        return product;
    }
}
