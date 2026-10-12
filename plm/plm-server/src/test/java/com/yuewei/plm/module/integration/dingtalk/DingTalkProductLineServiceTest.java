package com.yuewei.plm.module.integration.dingtalk;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.yuewei.plm.common.util.ProductCodeGenerator;
import com.yuewei.plm.module.integration.dingtalk.dto.DingTalkProductLineReceiveDTO;
import com.yuewei.plm.module.integration.dingtalk.entity.IntegrationRecord;
import com.yuewei.plm.module.integration.dingtalk.repository.IntegrationRecordRepository;
import com.yuewei.plm.module.integration.dingtalk.service.DingTalkAttachmentArchiveService;
import com.yuewei.plm.module.integration.dingtalk.service.DingTalkProductLineService;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.workflow.service.WorkflowTemplateService;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import java.time.LocalDate;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

class DingTalkProductLineServiceTest {

    @Test
    void approvedApprovalCreatesProductLineProject() {
        ProductRepository productRepository = mock(ProductRepository.class);
        IntegrationRecordRepository integrationRepository = mock(IntegrationRecordRepository.class);
        DingTalkAttachmentArchiveService attachmentArchiveService = mock(DingTalkAttachmentArchiveService.class);
        OperationLogService operationLogService = mock(OperationLogService.class);
        when(integrationRepository.selectList(any())).thenReturn(List.of());
        when(productRepository.selectCount(any())).thenReturn(0L);
        when(attachmentArchiveService.archiveMetadata(any(), any(), any(), any(), any())).thenReturn("archived_metadata");
        doAnswer(invocation -> {
            Product product = invocation.getArgument(0);
            product.setProductId(88L);
            return 1;
        }).when(productRepository).insert(any(Product.class));
        doAnswer(invocation -> {
            IntegrationRecord record = invocation.getArgument(0);
            record.setIntegrationRecordId(99L);
            return 1;
        }).when(integrationRepository).insert(any(IntegrationRecord.class));
        when(productRepository.selectById(88L)).thenAnswer(invocation -> {
            Product product = new Product();
            product.setProductId(88L);
            product.setProductCode("PRD-HA-0001");
            product.setProductName("超队 HA 新产品");
            product.setProductType("product_line");
            return product;
        });

        DingTalkProductLineService service = new DingTalkProductLineService(
            productRepository,
            integrationRepository,
            new ProductCodeGenerator(),
            attachmentArchiveService,
            operationLogService,
            mock(WorkflowTemplateService.class)
        );

        var result = service.receive(dto());

        assertThat(result.getProjectId()).isEqualTo(88L);
        assertThat(result.getStatus()).isEqualTo("success");
        assertThat(result.getAttachmentArchiveStatus()).isEqualTo("archived_metadata");
        ArgumentCaptor<Product> productCaptor = ArgumentCaptor.forClass(Product.class);
        verify(productRepository).insert(productCaptor.capture());
        assertThat(productCaptor.getValue().getProductType()).isEqualTo("product_line");
        assertThat(productCaptor.getValue().getStatus()).isEqualTo("developing");
        assertThat(productCaptor.getValue().getExpectedDeliveryDate()).isEqualTo(LocalDate.of(2026, 8, 30));
        assertThat(productCaptor.getValue().getSourceSystem()).isEqualTo("dingtalk");
        assertThat(productCaptor.getValue().getSourceInstanceId()).isEqualTo("DT-PRODUCT-001");
        assertThat(productCaptor.getValue().getProductCode()).isEqualTo("NHA4030");
        assertThat(productCaptor.getValue().getProductCodePrefix()).isEqualTo("HA");
        assertThat(productCaptor.getValue().getProductSpecificCode()).isEqualTo("HA");
        assertThat(productCaptor.getValue().getMoldCodePrefix()).isEqualTo("MHA");
        assertThat(productCaptor.getValue().getColor()).isEqualTo("black,white");
        assertThat(productCaptor.getValue().getMaterial()).isEqualTo("TPU,PC");
    }

    private DingTalkProductLineReceiveDTO dto() {
        DingTalkProductLineReceiveDTO dto = new DingTalkProductLineReceiveDTO();
        dto.setApprovalInstanceId("DT-PRODUCT-001");
        dto.setApprovalStatus("approved");
        dto.setProductName("超队 HA 新产品");
        dto.setProductCodePrefix("HA");
        dto.setMoldCodePrefix("MHA");
        dto.setProductionColors("black,white");
        dto.setMoldMaterials("TPU,PC");
        dto.setExpectedDeliveryDate(LocalDate.of(2026, 8, 30));
        dto.setApplicantUserName("tester");
        return dto;
    }
}
