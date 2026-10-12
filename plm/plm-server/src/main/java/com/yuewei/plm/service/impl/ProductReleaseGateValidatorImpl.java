package com.yuewei.plm.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.yuewei.plm.common.constant.ProductStatusConstants;
import com.yuewei.plm.module.attachment.constant.AttachmentOwnerTypeConstants;
import com.yuewei.plm.module.attachment.entity.Attachment;
import com.yuewei.plm.module.attachment.repository.AttachmentRepository;
import com.yuewei.plm.module.bom.entity.ProductBom;
import com.yuewei.plm.module.bom.repository.ProductBomRepository;
import com.yuewei.plm.module.process.entity.ProcessEntity;
import com.yuewei.plm.module.process.repository.ProcessRepository;
import com.yuewei.plm.module.project.constant.TimelineNodeConstants;
import com.yuewei.plm.module.project.constant.TimelineNodeConstants.TimelineNodeDefinition;
import com.yuewei.plm.module.project.service.TimelineDefinitionProvider;
import com.yuewei.plm.repository.entity.Product;
import com.yuewei.plm.service.ProductReleaseGateValidator;
import com.yuewei.plm.service.vo.ProductReleaseGateCheckVO;
import com.yuewei.plm.service.vo.ProductReleaseGateMissingItemVO;
import java.util.ArrayList;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class ProductReleaseGateValidatorImpl implements ProductReleaseGateValidator {

    private static final String PROCESS_TYPE_ROUTING = "routing";

    private final ProductBomRepository productBomRepository;
    private final ProcessRepository processRepository;
    private final AttachmentRepository attachmentRepository;
    private final TimelineDefinitionProvider timelineDefinitionProvider;

    @Override
    public ProductReleaseGateCheckVO check(Product product) {
        List<ProductReleaseGateMissingItemVO> missingItems = new ArrayList<>();
        List<ProductReleaseGateMissingItemVO> blockingItems = new ArrayList<>();
        String currentNodeKey = resolveCurrentNodeKey(product);
        boolean currentNodeConfirmed = Boolean.TRUE.equals(product.getTimelineCurrentConfirmed())
            && java.util.Objects.equals(currentNodeKey, product.getTimelineConfirmedNodeKey());

        if (ProductStatusConstants.ARCHIVED.equals(product.getStatus())) {
            blockingItems.add(missing("PRODUCT_ARCHIVED", "产品已归档，不能发布", "blocker"));
        }
        if ("abandoned".equals(product.getLockStatus())) {
            blockingItems.add(missing("PRODUCT_ABANDONED", "项目已废弃，不能发布", "blocker"));
        }
        if (!isAllowedPublishNode(product, currentNodeKey)) {
            blockingItems.add(missing("TIMELINE_NODE_NOT_ALLOWED", "当前时间轴未到允许发布的最终节点", "blocker"));
        }
        if (!currentNodeConfirmed) {
            blockingItems.add(missing("TIMELINE_NODE_NOT_CONFIRMED", "当前门禁节点尚未确认", "blocker"));
        }
        missingItems.addAll(blockingItems);

        int frozenBomCount = countFrozenBom(product.getProductId());
        int lockedProcessRouteCount = countLockedProcessRoute(product.getProductId());
        int drawingFileCount = countAttachment(product.getProductId(), List.of("drawing"));
        int sopFileCount = countAttachment(product.getProductId(), List.of("sop"));
        int sipFileCount = countAttachment(product.getProductId(), List.of("sip"));
        int testingFileCount = countAttachment(product.getProductId(), List.of("testing"));

        if (frozenBomCount <= 0) {
            missingItems.add(missing("BOM_NOT_FROZEN", "缺少已冻结或已发布 BOM", "warning"));
        }
        if (lockedProcessRouteCount <= 0) {
            missingItems.add(missing("PROCESS_ROUTE_NOT_LOCKED", "缺少已锁定或已冻结工艺路线", "warning"));
        }
        if (drawingFileCount <= 0) {
            missingItems.add(missing("DRAWING_FILE_MISSING", "缺少图纸文件", "warning"));
        }
        if (sopFileCount + sipFileCount <= 0) {
            missingItems.add(missing("SOP_OR_SIP_FILE_MISSING", "缺少 SOP 或 SIP 文件", "warning"));
        }
        if (testingFileCount <= 0) {
            missingItems.add(missing("TESTING_FILE_MISSING", "缺少测试资料", "warning"));
        }

        return ProductReleaseGateCheckVO.builder()
            .projectId(product.getProductId())
            .productId(product.getProductId())
            .passed(blockingItems.isEmpty())
            .blocking(!blockingItems.isEmpty())
            .confirmRequired(missingItems.stream().anyMatch(item -> "warning".equals(item.getSeverity())))
            .currentStatus(product.getStatus())
            .currentNodeKey(currentNodeKey)
            .currentNodeConfirmed(currentNodeConfirmed)
            .frozenBomCount(frozenBomCount)
            .lockedProcessRouteCount(lockedProcessRouteCount)
            .drawingFileCount(drawingFileCount)
            .sopFileCount(sopFileCount)
            .sipFileCount(sipFileCount)
            .testingFileCount(testingFileCount)
            .missingItems(missingItems)
            .build();
    }

    private String resolveCurrentNodeKey(Product product) {
        List<TimelineNodeDefinition> definitions = timelineDefinitionProvider.getDefinitions(product);
        if (definitions.isEmpty()) {
            return null;
        }
        int stepNo = product.getCurrentStepNo() == null ? 1 : product.getCurrentStepNo();
        int normalized = Math.min(Math.max(stepNo, 1), definitions.size());
        return definitions.get(normalized - 1).nodeCode();
    }

    private boolean isAllowedPublishNode(Product product, String currentNodeKey) {
        if (!TimelineNodeConstants.PRODUCT_TYPE_PRODUCT_LINE.equals(product.getProductType())
            && !TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT.equals(product.getProductType())) {
            return false;
        }
        List<TimelineNodeDefinition> definitions = timelineDefinitionProvider.getDefinitions(product);
        if (definitions.isEmpty()) {
            return false;
        }
        return definitions.get(definitions.size() - 1).nodeCode().equals(currentNodeKey);
    }

    private int countFrozenBom(Long productId) {
        Long count = productBomRepository.selectCount(new LambdaQueryWrapper<ProductBom>()
            .eq(ProductBom::getProductId, productId)
            .eq(ProductBom::getDeletedFlag, 0)
            .and(wrapper -> wrapper
                .eq(ProductBom::getFrozenFlag, 1)
                .or()
                .eq(ProductBom::getStatus, "released")));
        return count.intValue();
    }

    private int countLockedProcessRoute(Long productId) {
        Long count = processRepository.selectCount(new LambdaQueryWrapper<ProcessEntity>()
            .eq(ProcessEntity::getProductId, productId)
            .eq(ProcessEntity::getProcessType, PROCESS_TYPE_ROUTING)
            .eq(ProcessEntity::getDeletedFlag, 0)
            .in(ProcessEntity::getStatus, List.of("locked", "frozen")));
        return count.intValue();
    }

    private int countAttachment(Long productId, List<String> categories) {
        Long count = attachmentRepository.selectCount(new LambdaQueryWrapper<Attachment>()
            .eq(Attachment::getOwnerObjectType, AttachmentOwnerTypeConstants.PRODUCT)
            .eq(Attachment::getOwnerObjectId, productId)
            .eq(Attachment::getDeletedFlag, 0)
            .in(Attachment::getFileCategory, categories));
        return count.intValue();
    }

    private ProductReleaseGateMissingItemVO missing(String code, String message, String severity) {
        return ProductReleaseGateMissingItemVO.builder()
            .code(code)
            .message(message)
            .severity(severity)
            .build();
    }
}
