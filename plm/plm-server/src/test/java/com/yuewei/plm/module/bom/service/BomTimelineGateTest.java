package com.yuewei.plm.module.bom.service;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.module.project.service.TimelineDefinitionProvider;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import org.junit.jupiter.api.Test;

class BomTimelineGateTest {
    @Test
    void acceptsConfirmedProductLineReleaseNode() {
        ProductRepository repository = mock(ProductRepository.class);
        when(repository.selectById(10L)).thenReturn(product("product_line", "PRODUCT_LINE_PRODUCTION_DECISION_STEP", true));
        assertThatCode(() -> new BomTimelineGate(repository, new TimelineDefinitionProvider()).requireFreezeOrPublishNode(10L))
            .doesNotThrowAnyException();
    }

    @Test
    void acceptsConfirmedModelVariantFinalMoldTransferNode() {
        ProductRepository repository = mock(ProductRepository.class);
        when(repository.selectById(10L)).thenReturn(product("model_variant", "MODEL_VARIANT_MOLD_TRANSFER", true));
        assertThatCode(() -> new BomTimelineGate(repository, new TimelineDefinitionProvider()).requireFreezeOrPublishNode(10L))
            .doesNotThrowAnyException();
    }

    @Test
    void rejectsWrongNode() {
        ProductRepository repository = mock(ProductRepository.class);
        when(repository.selectById(10L)).thenReturn(product("model_variant", "MODEL_VARIANT_VERSION_FREEZE", true));
        assertThatThrownBy(() -> new BomTimelineGate(repository, new TimelineDefinitionProvider()).requireFreezeOrPublishNode(10L))
            .isInstanceOf(BusinessException.class).hasMessageContaining("时间轴节点");
    }

    private Product product(String type, String node, boolean confirmed) {
        Product product = new Product();
        product.setProductType(type);
        product.setTimelineConfirmedNodeKey(node);
        product.setTimelineCurrentConfirmed(confirmed);
        return product;
    }
}
