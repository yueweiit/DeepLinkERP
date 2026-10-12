package com.yuewei.plm.module.project.service.impl;

import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.constant.ProductStatusConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.yuewei.plm.module.attachment.constant.AttachmentOwnerTypeConstants;
import com.yuewei.plm.module.attachment.entity.Attachment;
import com.yuewei.plm.module.attachment.repository.AttachmentRepository;
import com.yuewei.plm.module.project.constant.TimelineNodeConstants;
import com.yuewei.plm.module.project.constant.TimelineNodeConstants.TimelineNodeDefinition;
import com.yuewei.plm.module.project.service.TimelineDefinitionProvider;
import com.yuewei.plm.module.project.service.TimelineService;
import com.yuewei.plm.module.project.service.MoldTransferExpressService;
import com.yuewei.plm.module.project.variant.entity.RequirementForm;
import com.yuewei.plm.module.project.variant.repository.RequirementFormRepository;
import com.yuewei.plm.module.project.vo.TimelineDetailVO;
import com.yuewei.plm.module.project.vo.TimelineNodeVO;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class TimelineServiceImpl implements TimelineService {

    private final ProductRepository productRepository;
    private final TimelineDefinitionProvider timelineDefinitionProvider;
    private final AttachmentRepository attachmentRepository;
    private final MoldTransferExpressService moldTransferExpressService;
    private final RequirementFormRepository requirementFormRepository;

    @Override
    public TimelineDetailVO getTimeline(Long projectId) {
        Product product = getProductOrThrow(projectId);
        List<TimelineNodeDefinition> definitions = timelineDefinitionProvider.getDefinitions(product);
        int currentStepNo = normalizeStepNo(product.getCurrentStepNo(), definitions.size());
        if (!isTimelineStarted(product)) {
            return TimelineDetailVO.builder()
                .projectId(product.getProductId())
                .productId(product.getProductId())
                .projectCode(product.getProductCode())
                .projectName(product.getProductName())
                .productType(product.getProductType())
                .expectedDeliveryDate(product.getExpectedDeliveryDate())
                .sourceSystem(product.getSourceSystem())
                .sourceInstanceId(product.getSourceInstanceId())
                .sourceFormUrl(product.getSourceFormUrl())
                .started(false)
                .startBlockReason("请先完成新型号项目信息完善表，确认后才能进入项目时间轴")
                .timelineCompleted(false)
                .currentStepNo(currentStepNo)
                .nodes(List.of())
                .build();
        }
        TimelineNodeDefinition currentNode = definitions.get(currentStepNo - 1);
        boolean timelineCompleted = isTimelineCompleted(product, currentStepNo, definitions.size(), currentNode);
        return TimelineDetailVO.builder()
            .projectId(product.getProductId())
            .productId(product.getProductId())
            .projectCode(product.getProductCode())
            .projectName(product.getProductName())
            .productType(product.getProductType())
            .expectedDeliveryDate(product.getExpectedDeliveryDate())
            .sourceSystem(product.getSourceSystem())
            .sourceInstanceId(product.getSourceInstanceId())
            .sourceFormUrl(product.getSourceFormUrl())
            .started(true)
            .startBlockReason(null)
            .timelineCompleted(timelineCompleted)
            .currentStepNo(currentStepNo)
            .currentStageCode(currentNode.stageCode())
            .currentStageName(currentNode.stageName())
            .currentPhaseName(currentNode.phaseName())
            .currentStepCode(currentNode.nodeCode())
            .currentStepName(currentStepName(product, currentNode))
            .currentConfirmed(isCurrentNodeConfirmed(product, currentNode))
            .confirmedNodeKey(product.getTimelineConfirmedNodeKey())
            .lastAction(product.getTimelineLastAction())
            .lastReason(product.getTimelineLastReason())
            .lastOperatedAt(product.getTimelineLastOperatedAt())
            .lastOperatorUserId(product.getTimelineLastOperatorUserId())
            .lastOperatorUserName(product.getTimelineLastOperatorUserName())
            .moldTransferExpress(moldTransferExpressService.getSnapshot(product.getProductId(), currentNode.nodeCode()))
            .nodes(definitions.stream()
                .map(definition -> toNodeVO(definition, currentStepNo, product.getProductId(), product, timelineCompleted))
                .toList())
            .build();
    }

    private boolean isTimelineStarted(Product product) {
        if (!TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT.equals(product.getProductType())) {
            return true;
        }
        RequirementForm form = requirementFormRepository.selectList(new LambdaQueryWrapper<RequirementForm>()
                .eq(RequirementForm::getProjectId, product.getProductId())
                .eq(RequirementForm::getDeletedFlag, 0))
            .stream()
            .findFirst()
            .orElse(null);
        return form != null && "confirmed".equals(form.getStatus());
    }

    private TimelineNodeVO toNodeVO(
        TimelineNodeDefinition definition,
        int currentStepNo,
        Long productId,
        Product product,
        boolean timelineCompleted
    ) {
        return TimelineNodeVO.builder()
            .stepNo(definition.stepNo())
            .nodeCode(definition.nodeCode())
            .nodeName(definition.nodeName())
            .stageCode(definition.stageCode())
            .stageName(definition.stageName())
            .phaseName(definition.phaseName())
            .requiredAttachment(definition.requiredAttachment())
            .requiredFileCategory(definition.requiredFileCategory())
            .uploadPrompt(definition.uploadPrompt())
            .confirmPrompt(definition.confirmPrompt())
            .emptyFileMessage(definition.emptyFileMessage())
            .gateFlag(definition.gateFlag())
            .enabledFlag(definition.enabledFlag())
            .nodeStatus(resolveNodeStatus(definition.stepNo(), currentStepNo, timelineCompleted))
            .documentCount(countDocuments(productId, definition.nodeCode()))
            .confirmed(isCurrentNodeConfirmed(product, definition))
            .build();
    }

    private boolean isCurrentNodeConfirmed(Product product, TimelineNodeDefinition definition) {
        return Boolean.TRUE.equals(product.getTimelineCurrentConfirmed())
            && definition.nodeCode().equals(product.getTimelineConfirmedNodeKey());
    }

    private String currentStepName(Product product, TimelineNodeDefinition currentNode) {
        return isCompletedModelVariant(product) ? "已完结" : currentNode.nodeName();
    }

    private String resolveNodeStatus(int stepNo, int currentStepNo, boolean timelineCompleted) {
        if (timelineCompleted && stepNo <= currentStepNo) {
            return TimelineNodeConstants.NODE_STATUS_COMPLETED;
        }
        if (stepNo < currentStepNo) {
            return TimelineNodeConstants.NODE_STATUS_COMPLETED;
        }
        if (stepNo == currentStepNo) {
            return TimelineNodeConstants.NODE_STATUS_CURRENT;
        }
        return TimelineNodeConstants.NODE_STATUS_PENDING;
    }

    private boolean isTimelineCompleted(
        Product product,
        int currentStepNo,
        int maxStepNo,
        TimelineNodeDefinition currentNode
    ) {
        return currentStepNo >= maxStepNo
            && Boolean.TRUE.equals(product.getTimelineCurrentConfirmed())
            && currentNode.nodeCode().equals(product.getTimelineConfirmedNodeKey())
            && isTerminalProductStatus(product.getStatus());
    }

    private boolean isTerminalProductStatus(String status) {
        return ProductStatusConstants.RELEASED.equals(status)
            || ProductStatusConstants.ARCHIVED.equals(status);
    }

    private boolean isCompletedModelVariant(Product product) {
        return TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT.equals(product.getProductType())
            && ProductStatusConstants.ARCHIVED.equals(product.getStatus());
    }

    private int countDocuments(Long productId, String nodeCode) {
        Long count = attachmentRepository.selectCount(new LambdaQueryWrapper<Attachment>()
            .eq(Attachment::getOwnerObjectType, AttachmentOwnerTypeConstants.PRODUCT)
            .eq(Attachment::getOwnerObjectId, productId)
            .eq(Attachment::getTimelineNodeKey, nodeCode)
            .eq(Attachment::getDeletedFlag, 0));
        return count == null ? 0 : count.intValue();
    }

    private int normalizeStepNo(Integer currentStepNo, int maxStepNo) {
        if (currentStepNo == null || currentStepNo < 1) {
            return 1;
        }
        return Math.min(currentStepNo, maxStepNo);
    }

    private Product getProductOrThrow(Long projectId) {
        Product product = productRepository.selectById(projectId);
        if (product == null || Integer.valueOf(1).equals(product.getDeletedFlag())) {
            throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "项目不存在");
        }
        return product;
    }
}
