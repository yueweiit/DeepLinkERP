package com.yuewei.plm.module.project.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.module.project.constant.TimelineNodeConstants;
import com.yuewei.plm.module.project.constant.TimelineNodeConstants.TimelineNodeDefinition;
import com.yuewei.plm.module.workflow.service.WorkflowDefinitionProvider;
import com.yuewei.plm.repository.entity.Product;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

class TimelineDefinitionProviderTest {

    private final TimelineDefinitionProvider provider = new TimelineDefinitionProvider();

    @Test
    void returnsProductLineSmallStepsInFixedOrder() {
        var definitions = provider.getDefinitions(TimelineNodeConstants.PRODUCT_TYPE_PRODUCT_LINE);

        assertThat(definitions).hasSize(22);
        assertThat(definitions.get(0).stepNo()).isEqualTo(1);
        assertThat(definitions.get(0).nodeCode()).isEqualTo("PRODUCT_LINE_INIT_CREATE");
        assertThat(definitions.get(0).stageCode()).isEqualTo("PRODUCT_LINE_INIT_CONFIRM");
        assertThat(definitions.get(0).requiredFileCategory()).isEqualTo("other");
        assertThat(definitions.get(21).stepNo()).isEqualTo(22);
        assertThat(definitions.get(21).nodeCode()).isEqualTo("PRODUCT_LINE_PRODUCTION_DECISION_STEP");
        assertThat(definitions.get(21).stageCode()).isEqualTo("PRODUCT_LINE_PRODUCTION_DECISION");
    }

    @Test
    void returnsModelVariantSmallStepsInFixedOrder() {
        var definitions = provider.getDefinitions(TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT);

        assertThat(definitions).hasSize(18);
        assertThat(definitions.get(0).nodeCode()).isEqualTo("MODEL_VARIANT_INIT_CREATE");
        assertThat(definitions.get(0).stageCode()).isEqualTo("MODEL_VARIANT_INIT_CONFIRM");
        assertThat(definitions.get(17).nodeCode()).isEqualTo("MODEL_VARIANT_MOLD_TRANSFER");
        assertThat(definitions.get(17).stageCode()).isEqualTo("MODEL_VARIANT_SMALL_BATCH_MX");
    }

    @Test
    void trimsDynamicModelVariantDefinitionsAtMoldTransfer() {
        TimelineDefinitionProvider provider = new TimelineDefinitionProvider();
        WorkflowDefinitionProvider workflowDefinitionProvider = mock(WorkflowDefinitionProvider.class);
        ReflectionTestUtils.setField(provider, "workflowDefinitionProvider", workflowDefinitionProvider);
        when(workflowDefinitionProvider.getDefinitions(TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT))
            .thenReturn(List.of(
                definition(17, "MODEL_VARIANT_SMALL_BATCH_TEST"),
                definition(18, "MODEL_VARIANT_MOLD_TRANSFER"),
                definition(19, "MODEL_VARIANT_MX_ACCEPTANCE"),
                definition(22, "MODEL_VARIANT_RELEASE")
            ));

        var definitions = provider.getDefinitions(TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT);

        assertThat(definitions).hasSize(2);
        assertThat(definitions.get(1).nodeCode()).isEqualTo("MODEL_VARIANT_MOLD_TRANSFER");
    }

    @Test
    void trimsProductSpecificDynamicModelVariantDefinitionsAtMoldTransfer() {
        TimelineDefinitionProvider provider = new TimelineDefinitionProvider();
        WorkflowDefinitionProvider workflowDefinitionProvider = mock(WorkflowDefinitionProvider.class);
        ReflectionTestUtils.setField(provider, "workflowDefinitionProvider", workflowDefinitionProvider);
        Product product = new Product();
        product.setProductType(TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT);
        when(workflowDefinitionProvider.getDefinitions(product)).thenReturn(List.of(
            definition(18, "MODEL_VARIANT_MOLD_TRANSFER"),
            definition(19, "MODEL_VARIANT_MX_ACCEPTANCE")
        ));

        var definitions = provider.getDefinitions(product);

        assertThat(definitions).hasSize(1);
        assertThat(definitions.get(0).nodeCode()).isEqualTo("MODEL_VARIANT_MOLD_TRANSFER");
    }

    @Test
    void usesModelVariantWorkflowDefinitionsForSkuProducts() {
        TimelineDefinitionProvider provider = new TimelineDefinitionProvider();
        WorkflowDefinitionProvider workflowDefinitionProvider = mock(WorkflowDefinitionProvider.class);
        ReflectionTestUtils.setField(provider, "workflowDefinitionProvider", workflowDefinitionProvider);
        Product sku = new Product();
        sku.setProductType(TimelineNodeConstants.PRODUCT_TYPE_SKU);
        when(workflowDefinitionProvider.getDefinitions(TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT))
            .thenReturn(List.of(
                definition(18, "MODEL_VARIANT_MOLD_TRANSFER"),
                definition(19, "MODEL_VARIANT_MX_ACCEPTANCE")
            ));

        var definitions = provider.getDefinitions(sku);

        assertThat(definitions).hasSize(1);
        assertThat(definitions.get(0).nodeCode()).isEqualTo("MODEL_VARIANT_MOLD_TRANSFER");
    }

    @Test
    void clampsCurrentNodeNameToKnownRange() {
        assertThat(provider.getCurrentNodeName(TimelineNodeConstants.PRODUCT_TYPE_PRODUCT_LINE, -1)).isNotBlank();
        assertThat(provider.getCurrentNodeName(TimelineNodeConstants.PRODUCT_TYPE_PRODUCT_LINE, 99)).isNotBlank();
    }

    @Test
    void exposesStageHelpersForGateAndUploadScope() {
        var step1 = provider.getDefinitionByCode(
            TimelineNodeConstants.PRODUCT_TYPE_PRODUCT_LINE,
            "PRODUCT_LINE_INIT_CREATE"
        );
        var step2 = provider.getDefinitionByStepNo(TimelineNodeConstants.PRODUCT_TYPE_PRODUCT_LINE, 2);

        assertThat(step1.stageCode()).isEqualTo("PRODUCT_LINE_INIT_CONFIRM");
        assertThat(step2.nodeCode()).isEqualTo("PRODUCT_LINE_INIT_APPROVE");
        assertThat(provider.isLastStepOfStage(TimelineNodeConstants.PRODUCT_TYPE_PRODUCT_LINE, step2)).isTrue();
        assertThat(provider.getStageStepCodes(TimelineNodeConstants.PRODUCT_TYPE_PRODUCT_LINE, "PRODUCT_LINE_INIT_CONFIRM"))
            .containsExactly("PRODUCT_LINE_INIT_CREATE", "PRODUCT_LINE_INIT_APPROVE");
        assertThat(provider.getRequiredDefinitionsForStage(
            TimelineNodeConstants.PRODUCT_TYPE_PRODUCT_LINE,
            "PRODUCT_LINE_INIT_CONFIRM"
        )).extracting("nodeCode").containsExactly("PRODUCT_LINE_INIT_CREATE");
    }

    @Test
    void rejectsUnsupportedProductType() {
        assertThatThrownBy(() -> provider.getDefinitions("unknown"))
            .isInstanceOf(BusinessException.class)
            .extracting("code")
            .isEqualTo(ErrorCodeConstants.VALIDATION_ERROR);
    }

    private TimelineNodeDefinition definition(int stepNo, String nodeCode) {
        return new TimelineNodeDefinition(stepNo, nodeCode, nodeCode);
    }
}
