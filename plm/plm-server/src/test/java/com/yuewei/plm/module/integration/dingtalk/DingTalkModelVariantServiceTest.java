package com.yuewei.plm.module.integration.dingtalk;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.util.ProductBusinessCodeGenerator;
import com.yuewei.plm.common.util.ProductCodeGenerator;
import com.yuewei.plm.module.bom.entity.ProductProductionColorDecision;
import com.yuewei.plm.module.bom.repository.ProductProductionColorDecisionRepository;
import com.yuewei.plm.module.integration.dingtalk.dto.DingTalkModelVariantReceiveDTO;
import com.yuewei.plm.module.integration.dingtalk.entity.IntegrationRecord;
import com.yuewei.plm.module.integration.dingtalk.repository.IntegrationRecordRepository;
import com.yuewei.plm.module.integration.dingtalk.service.DingTalkAttachmentArchiveService;
import com.yuewei.plm.module.integration.dingtalk.service.DingTalkModelVariantService;
import com.yuewei.plm.module.integration.dingtalk.service.MoldCodeIntakeService;
import com.yuewei.plm.module.integration.dingtalk.vo.MoldCodeMatchVO;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.bom.service.BomInheritanceService;
import com.yuewei.plm.module.process.service.ProcessRouteInheritanceService;
import com.yuewei.plm.module.order.entity.OrderEntity;
import com.yuewei.plm.module.workflow.service.WorkflowTemplateService;
import com.yuewei.plm.module.order.service.OrderService;
import com.yuewei.plm.module.project.variant.dto.RequirementFormSaveDTO;
import com.yuewei.plm.module.project.variant.repository.ProductVariantColorRepository;
import com.yuewei.plm.module.project.variant.repository.RequirementFormRepository;
import com.yuewei.plm.module.project.variant.entity.RequirementForm;
import com.yuewei.plm.module.product.mold.service.ProductMoldCodeService;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;

class DingTalkModelVariantServiceTest {
    @Test
    void approvedIntakeCreatesProjectWithAllConfirmedColorsSelected() {
        Fixture fixture = fixture();
        when(fixture.productRepository.selectById(5L)).thenReturn(parent());
        when(fixture.colorDecisionRepository.selectList(Mockito.<Wrapper<ProductProductionColorDecision>>any()))
            .thenReturn(List.of(color(10L, "01", "黑色"), color(11L, "02", "透明色")));
        when(fixture.integrationRepository.selectList(any())).thenReturn(List.of());
        when(fixture.moldCodeIntakeService.sync(any(), any(), any())).thenReturn(List.of(MoldCodeMatchVO.builder()
            .moldCode("MFA101291").expectedMoldCode("MFA101291").productSpecificCode("FA")
            .materialCode("10").phoneModelCode("1291").matchStatus("created_draft").inventoryId(100L).build()));

        var result = fixture.service.receive(receive());

        assertThat(result.getProjectId()).isNotNull();
        assertThat(result.getMoldMatches()).extracting(MoldCodeMatchVO::getMoldCode).containsExactly("MFA101291");
        ArgumentCaptor<Product> projectCaptor = ArgumentCaptor.forClass(Product.class);
        verify(fixture.productRepository).insert(projectCaptor.capture());
        assertThat(projectCaptor.getValue().getStatus()).isEqualTo("developing");
        assertThat(projectCaptor.getValue().getProductName()).isEqualTo("精孔磁吸壳 iPhone 18");
        assertThat(projectCaptor.getValue().getProductSpecificCode()).isEqualTo("FA");
        assertThat(projectCaptor.getValue().getPhoneModelCode()).isEqualTo("1291");
        ArgumentCaptor<RequirementForm> formCaptor = ArgumentCaptor.forClass(RequirementForm.class);
        verify(fixture.formRepository).insert(formCaptor.capture());
        assertThat(formCaptor.getValue().getMoldMatchStatus()).isEqualTo("created_draft");
        assertThat(formCaptor.getValue().getMoldMatchJson()).contains("MFA101291");
        ArgumentCaptor<com.yuewei.plm.module.project.variant.entity.ProductVariantColor> captor =
            ArgumentCaptor.forClass(com.yuewei.plm.module.project.variant.entity.ProductVariantColor.class);
        verify(fixture.variantColorRepository, Mockito.times(2)).insert(captor.capture());
        assertThat(captor.getAllValues()).allMatch(value -> value.getSelectedFlag() == 1 && value.getDefaultSelectedFlag() == 1);
        verify(fixture.processRouteInheritanceService).inheritLatestReleasedFormalBomRoutesByColors(
            Mockito.eq(5L),
            Mockito.eq(projectCaptor.getValue()),
            Mockito.eq(List.of("黑色", "透明色")),
            Mockito.eq("tester")
        );
        verify(fixture.bomInheritanceService).inheritLatestReleasedByColors(5L, 9L, List.of("黑色", "透明色"), Map.of(27L, 200L));
    }

    @Test
    void approvedIntakeBackfillsPhoneModelCodeBeforeInheritingProcessRoutesAndBom() {
        Fixture fixture = fixture();
        Product parent = parent();
        parent.setProductSpecificCode("BA");
        when(fixture.productRepository.selectById(5L)).thenReturn(parent);
        when(fixture.colorDecisionRepository.selectList(Mockito.<Wrapper<ProductProductionColorDecision>>any()))
            .thenReturn(List.of(color(10L, "01", "黑色")));
        when(fixture.integrationRepository.selectList(any())).thenReturn(List.of());
        doAnswer(invocation -> {
            DingTalkModelVariantReceiveDTO dto = invocation.getArgument(0);
            dto.setProductSpecificCode("BA");
            dto.setPhoneModelCode("1296");
            dto.setMaterialCodes(List.of("10"));
            dto.setMoldCodes("MBA101296");
            return List.of(MoldCodeMatchVO.builder()
                .moldCode("MBA101296")
                .expectedMoldCode("MBA101296")
                .productSpecificCode("BA")
                .materialCode("10")
                .phoneModelCode("1296")
                .matchStatus("linked_existing")
                .inventoryId(100L)
                .build());
        }).when(fixture.moldCodeIntakeService).sync(any(), any(), any());

        DingTalkModelVariantReceiveDTO dto = receive();
        dto.setProductSpecificCode(null);
        dto.setPhoneModelCode(null);
        dto.setMoldCodes("MBA101296");

        fixture.service.receive(dto);

        ArgumentCaptor<Product> inheritanceProductCaptor = ArgumentCaptor.forClass(Product.class);
        verify(fixture.processRouteInheritanceService).inheritLatestReleasedFormalBomRoutesByColors(
            Mockito.eq(5L),
            inheritanceProductCaptor.capture(),
            Mockito.eq(List.of("黑色")),
            Mockito.eq("tester")
        );
        assertThat(inheritanceProductCaptor.getValue().getProductSpecificCode()).isEqualTo("BA");
        assertThat(inheritanceProductCaptor.getValue().getPhoneModelCode()).isEqualTo("1296");
        verify(fixture.productRepository).updateById(inheritanceProductCaptor.getValue());
        verify(fixture.bomInheritanceService).inheritLatestReleasedByColors(5L, 9L, List.of("黑色"), Map.of(27L, 200L));
    }

    @Test
    void approvedIntakeInfersParentProductFromMoldCodeProductSpecificCode() {
        Fixture fixture = fixture();
        Product parent = parent();
        parent.setProductId(50L);
        parent.setProductName("超队Súper Capitán");
        parent.setProductSpecificCode("HA");
        when(fixture.productMoldCodeService.findByIncomingMoldCodes(any())).thenReturn(Optional.of(parent));
        when(fixture.colorDecisionRepository.selectList(Mockito.<Wrapper<ProductProductionColorDecision>>any()))
            .thenReturn(List.of(color(10L, "01", "黑色")));
        when(fixture.integrationRepository.selectList(any())).thenReturn(List.of());
        DingTalkModelVariantReceiveDTO dto = receive();
        dto.setParentProductId(null);
        dto.setProductSpecificCode(null);
        dto.setPhoneModelCode(null);
        dto.setMaterialCodes(null);
        dto.setMoldCodes("MHA101296 / MHA201296");

        fixture.service.receive(dto);

        ArgumentCaptor<Product> projectCaptor = ArgumentCaptor.forClass(Product.class);
        verify(fixture.productRepository).insert(projectCaptor.capture());
        assertThat(dto.getParentProductId()).isEqualTo(50L);
        assertThat(projectCaptor.getValue().getParentProductId()).isEqualTo(50L);
        verify(fixture.moldCodeIntakeService).sync(any(), Mockito.eq(parent), any());
    }

    @Test
    void approvedIntakeRejectsParentProductIdThatConflictsWithMoldCode() {
        Fixture fixture = fixture();
        Product parent = parent();
        parent.setProductSpecificCode("BA");
        when(fixture.productRepository.selectById(5L)).thenReturn(parent);
        when(fixture.integrationRepository.selectList(any())).thenReturn(List.of());
        DingTalkModelVariantReceiveDTO dto = receive();
        dto.setMoldCodes("MHA101296");

        assertThatThrownBy(() -> fixture.service.receive(dto))
            .isInstanceOf(BusinessException.class)
            .hasMessageContaining("来源产品ID与模具编码产品特定编码不一致");

        verify(fixture.productRepository, never()).insert(any(Product.class));
    }

    @Test
    void approvedIntakeRejectsParentProductIdThatConflictsWithImportedMoldCodeRelation() {
        Fixture fixture = fixture();
        Product explicitParent = parent();
        explicitParent.setProductId(5L);
        Product relationParent = parent();
        relationParent.setProductId(50L);
        relationParent.setProductSpecificCode("HA");
        when(fixture.productRepository.selectById(5L)).thenReturn(explicitParent);
        when(fixture.integrationRepository.selectList(any())).thenReturn(List.of());
        when(fixture.productMoldCodeService.findByIncomingMoldCodes(any())).thenReturn(Optional.of(relationParent));
        DingTalkModelVariantReceiveDTO dto = receive();
        dto.setMoldCodes("MHA101296");

        assertThatThrownBy(() -> fixture.service.receive(dto))
            .isInstanceOf(BusinessException.class)
            .hasMessageContaining("来源产品ID与模具编码关联产品不一致");

        verify(fixture.productRepository, never()).insert(any(Product.class));
    }

    @Test
    void approvedIntakeSkipsProductCodesThatAlreadyExist() {
        Fixture fixture = fixture();
        when(fixture.productRepository.selectById(5L)).thenReturn(parent());
        when(fixture.colorDecisionRepository.selectList(Mockito.<Wrapper<ProductProductionColorDecision>>any()))
            .thenReturn(List.of(color(10L, "01", "黑色")));
        when(fixture.integrationRepository.selectList(any())).thenReturn(List.of());
        when(fixture.productRepository.selectCount(any())).thenReturn(1L, 0L);

        fixture.service.receive(receive());

        ArgumentCaptor<Product> projectCaptor = ArgumentCaptor.forClass(Product.class);
        verify(fixture.productRepository).insert(projectCaptor.capture());
        assertThat(projectCaptor.getValue().getProductCode()).endsWith("0002");
    }

    @Test
    void approvedIntakeAllowsSameModelFromDifferentApprovalInstance() {
        Fixture fixture = fixture();
        Product existing = parent();
        existing.setProductId(99L);
        existing.setProductType("model_variant");
        existing.setParentProductId(5L);
        existing.setModel("iPhone 18");
        existing.setVersionNo("A");
        existing.setStatus("developing");
        when(fixture.productRepository.selectById(5L)).thenReturn(parent());
        when(fixture.colorDecisionRepository.selectList(Mockito.<Wrapper<ProductProductionColorDecision>>any()))
            .thenReturn(List.of(color(10L, "01", "黑色")));
        when(fixture.integrationRepository.selectList(any())).thenReturn(List.of());
        when(fixture.productRepository.selectList(any())).thenReturn(List.of(existing));
        doAnswer(invocation -> {
            com.yuewei.plm.module.integration.dingtalk.entity.IntegrationRecord record = invocation.getArgument(0);
            record.setIntegrationRecordId(701L);
            return 1;
        }).when(fixture.integrationRepository)
            .insert(any(com.yuewei.plm.module.integration.dingtalk.entity.IntegrationRecord.class));

        var result = fixture.service.receive(receive());

        assertThat(result.getProjectId()).isEqualTo(9L);
        assertThat(result.isIdempotentHit()).isFalse();
        verify(fixture.productRepository).insert(any(Product.class));
        verify(fixture.integrationRepository)
            .insert(any(com.yuewei.plm.module.integration.dingtalk.entity.IntegrationRecord.class));
    }

    @Test
    void repeatedApprovalInstanceWithDifferentApprovalNoThrowsMappingError() {
        Fixture fixture = fixture();
        IntegrationRecord existing = inboundRecord(
            19L,
            42L,
            "111",
            "{\"approvalNo\":\"DT-OLD-001\",\"form\":{\"parentProductId\":5,\"tipo\":\"Old Tipo\",\"model\":\"Old Model\",\"generatedCode\":\"MFA100001\"}}"
        );
        when(fixture.integrationRepository.selectList(any())).thenReturn(List.of(existing));
        DingTalkModelVariantReceiveDTO dto = receive();
        dto.setApprovalInstanceId("111");
        dto.setDingTalkApprovalNo("DT-NEW-002");
        dto.setModel("HR X8D");

        assertThatThrownBy(() -> fixture.service.receive(dto))
            .isInstanceOf(BusinessException.class)
            .hasMessageContaining("approvalInstanceId")
            .hasMessageContaining("固定值");

        verify(fixture.productRepository, never()).insert(any(Product.class));
    }

    @Test
    void confirmRequiresAtLeastOneColorAndCreatesOrderOnlyAfterConfirmation() {
        Fixture fixture = fixture();
        Product project = parent(); project.setProductId(9L); project.setProductType("model_variant"); project.setModel("iPhone 18");
        when(fixture.productRepository.selectById(9L)).thenReturn(project);
        RequirementForm form = new RequirementForm(); form.setProjectId(9L); form.setDingTalkApprovalNo("DT-20260720-001"); form.setStatus("draft"); form.setDeletedFlag(0);
        when(fixture.formRepository.selectList(any())).thenReturn(List.of(form));
        when(fixture.variantColorRepository.selectList(any())).thenReturn(List.of());

        RequirementFormSaveDTO dto = new RequirementFormSaveDTO();
        dto.setRequirementType("customer_requirement");
        dto.setCustomerRequirement("客户要求");
        dto.setSelectedVariantColorIds(List.of());

        assertThatThrownBy(() -> fixture.service.confirmRequirementForm(9L, dto))
            .isInstanceOf(BusinessException.class).hasMessageContaining("至少保留一个生产颜色");
    }

    @Test
    void confirmingRequirementFormCreatesOrderAndStartsFirstFormalTimelineNode() {
        Fixture fixture = fixture();
        Product project = parent();
        project.setProductId(9L);
        project.setProductType("model_variant");
        project.setModel("iPhone 18");
        project.setStatus("draft");
        project.setCurrentStepNo(1);
        when(fixture.productRepository.selectById(9L)).thenReturn(project);

        RequirementForm form = new RequirementForm();
        form.setProjectId(9L);
        form.setDingTalkApprovalNo("DT-20260720-001");
        form.setStatus("draft");
        form.setDeletedFlag(0);
        when(fixture.formRepository.selectList(any())).thenReturn(List.of(form));

        var variantColor = new com.yuewei.plm.module.project.variant.entity.ProductVariantColor();
        variantColor.setVariantColorId(101L);
        variantColor.setProjectProductId(9L);
        variantColor.setSelectedFlag(1);
        variantColor.setDeletedFlag(0);
        when(fixture.variantColorRepository.selectList(any())).thenReturn(List.of(variantColor));

        OrderEntity order = new OrderEntity();
        order.setOrderId(1001L);
        when(fixture.orderService.findByProjectId(9L)).thenReturn(null);
        when(fixture.orderService.create(any())).thenReturn(order);
        when(fixture.integrationRepository.selectList(any())).thenReturn(List.of());

        RequirementFormSaveDTO dto = new RequirementFormSaveDTO();
        dto.setRequirementType("market_requirement");
        dto.setSelectedVariantColorIds(List.of(101L));

        fixture.service.confirmRequirementForm(9L, dto);

        assertThat(form.getStatus()).isEqualTo("confirmed");
        assertThat(project.getCurrentStepNo()).isEqualTo(1);
        assertThat(project.getStatus()).isEqualTo("developing");
        assertThat(project.getTimelineCurrentConfirmed()).isFalse();
        verify(fixture.orderService).create(any());
        verify(fixture.operationLogService).logSuccess(argThat(command ->
            command.getAction().equals("MODEL_VARIANT_REQUIREMENT_FORM_CONFIRM")
                && command.getDetailJson().contains("\"currentNodeKey\":\"MODEL_VARIANT_INIT_CREATE\"")
                && command.getDetailJson().contains("\"orderId\":1001")
        ));
    }

    private Fixture fixture() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProductProductionColorDecisionRepository colorDecisionRepository = mock(ProductProductionColorDecisionRepository.class);
        IntegrationRecordRepository integrationRepository = mock(IntegrationRecordRepository.class);
        RequirementFormRepository formRepository = mock(RequirementFormRepository.class);
        ProductVariantColorRepository variantColorRepository = mock(ProductVariantColorRepository.class);
        OrderService orderService = mock(OrderService.class);
        MoldCodeIntakeService moldCodeIntakeService = mock(MoldCodeIntakeService.class);
        ProductMoldCodeService productMoldCodeService = mock(ProductMoldCodeService.class);
        DingTalkAttachmentArchiveService attachmentArchiveService = mock(DingTalkAttachmentArchiveService.class);
        OperationLogService operationLogService = mock(OperationLogService.class);
        ProcessRouteInheritanceService processRouteInheritanceService = mock(ProcessRouteInheritanceService.class);
        BomInheritanceService bomInheritanceService = mock(BomInheritanceService.class);
        when(productMoldCodeService.findByIncomingMoldCodes(any())).thenReturn(Optional.empty());
        when(attachmentArchiveService.archiveMetadata(any(), any(), any(), any(), any())).thenReturn("not_provided");
        when(processRouteInheritanceService.inheritLatestReleasedFormalBomRoutesByColors(any(), any(), any(), any()))
            .thenReturn(Map.of(27L, 200L));
        doAnswer(invocation -> {
            Product value = invocation.getArgument(0);
            value.setProductId(9L);
            return 1;
        }).when(productRepository).insert(any(Product.class));
        DingTalkModelVariantService service = new DingTalkModelVariantService(productRepository, colorDecisionRepository,
            integrationRepository, formRepository, variantColorRepository, orderService, new ProductCodeGenerator(),
            new ProductBusinessCodeGenerator(),
            moldCodeIntakeService, attachmentArchiveService, operationLogService, new ObjectMapper(), mock(WorkflowTemplateService.class),
            productMoldCodeService, processRouteInheritanceService, bomInheritanceService);
        return new Fixture(service, productRepository, colorDecisionRepository, integrationRepository, formRepository,
            variantColorRepository, moldCodeIntakeService, productMoldCodeService, processRouteInheritanceService, bomInheritanceService,
            operationLogService, orderService);
    }

    private DingTalkModelVariantReceiveDTO receive() {
        DingTalkModelVariantReceiveDTO dto = new DingTalkModelVariantReceiveDTO();
        dto.setDingTalkApprovalNo("DT-20260720-001"); dto.setApprovalStatus("approved"); dto.setParentProductId(5L);
        dto.setModel("iPhone 18"); dto.setTipo("精孔磁吸壳"); dto.setPriority("general"); dto.setCreatedBy("tester");
        dto.setProductSpecificCode("FA"); dto.setPhoneModelCode("1291"); dto.setMaterialCodes(List.of("10")); dto.setMoldCodes("MFA101291");
        return dto;
    }

    private Product parent() {
        Product value = new Product(); value.setProductId(5L); value.setProductName("超队 3.0"); value.setProductType("product_line");
        value.setProductSpecificCode("FA"); value.setSeriesName("超队"); value.setVersionNo("A"); value.setStatus("released"); value.setDeletedFlag(0); return value;
    }

    private ProductProductionColorDecision color(Long id, String code, String name) {
        ProductProductionColorDecision value = new ProductProductionColorDecision(); value.setProductProductionColorDecisionId(id);
        value.setProductId(5L); value.setCodeItemId(id); value.setColorCode(code); value.setColorName(name);
        value.setDecisionBatchNo("B1"); value.setSelectedFlag(1); value.setStatus("confirmed"); value.setDeletedFlag(0); return value;
    }

    private IntegrationRecord inboundRecord(Long recordId, Long projectId, String externalInstanceId, String payload) {
        IntegrationRecord record = new IntegrationRecord();
        record.setIntegrationRecordId(recordId);
        record.setSourceSystem("dingtalk");
        record.setIntegrationType("model_variant");
        record.setExternalInstanceId(externalInstanceId);
        record.setExternalStatus("approved");
        record.setProcessingStatus("success");
        record.setProjectId(projectId);
        record.setSourcePayloadJson(payload);
        record.setDeletedFlag(0);
        return record;
    }

    private record Fixture(DingTalkModelVariantService service, ProductRepository productRepository,
                           ProductProductionColorDecisionRepository colorDecisionRepository,
                           IntegrationRecordRepository integrationRepository, RequirementFormRepository formRepository,
                           ProductVariantColorRepository variantColorRepository, MoldCodeIntakeService moldCodeIntakeService,
                           ProductMoldCodeService productMoldCodeService,
                           ProcessRouteInheritanceService processRouteInheritanceService,
                           BomInheritanceService bomInheritanceService,
                           OperationLogService operationLogService,
                           OrderService orderService) {}
}
