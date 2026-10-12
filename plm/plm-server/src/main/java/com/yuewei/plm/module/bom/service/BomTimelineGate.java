package com.yuewei.plm.module.bom.service;

import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.module.project.constant.TimelineNodeConstants.TimelineNodeDefinition;
import com.yuewei.plm.module.project.service.TimelineDefinitionProvider;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class BomTimelineGate {
    private final ProductRepository productRepository;
    private final TimelineDefinitionProvider timelineDefinitionProvider;

    public void requireFreezeOrPublishNode(Long productId) {
        Product product = productRepository.selectById(productId);
        if (product == null || !Boolean.TRUE.equals(product.getTimelineCurrentConfirmed())) throw rejected();
        List<TimelineNodeDefinition> definitions = timelineDefinitionProvider.getDefinitions(product);
        String expected = definitions.isEmpty() ? null : definitions.get(definitions.size() - 1).nodeCode();
        if (expected == null || !expected.equals(product.getTimelineConfirmedNodeKey())) throw rejected();
    }

    private BusinessException rejected() {
        return new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "当前工作台时间轴节点不允许冻结或发布 BOM");
    }
}
