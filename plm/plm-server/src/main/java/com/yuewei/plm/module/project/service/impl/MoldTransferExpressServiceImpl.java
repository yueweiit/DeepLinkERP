package com.yuewei.plm.module.project.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.common.security.CurrentUserContext;
import com.yuewei.plm.module.operationlog.constant.OperationActionConstants;
import com.yuewei.plm.module.operationlog.service.OperationLogCreateCommand;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.project.constant.TimelineNodeConstants;
import com.yuewei.plm.module.project.constant.TimelineNodeConstants.TimelineNodeDefinition;
import com.yuewei.plm.module.project.dto.MoldTransferExpressSaveDTO;
import com.yuewei.plm.module.project.entity.ProjectMoldTransferExpress;
import com.yuewei.plm.module.project.repository.ProjectMoldTransferExpressRepository;
import com.yuewei.plm.module.project.service.MoldTransferExpressService;
import com.yuewei.plm.module.project.service.TimelineDefinitionProvider;
import com.yuewei.plm.module.project.vo.MoldTransferExpressVO;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import jakarta.servlet.http.HttpServletRequest;
import java.time.LocalDateTime;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

@Service
@RequiredArgsConstructor
public class MoldTransferExpressServiceImpl implements MoldTransferExpressService {

    private static final String PRODUCT_LINE_MOLD_TRANSFER = "PRODUCT_LINE_MOLD_TRANSFER";
    private static final String MODEL_VARIANT_MOLD_TRANSFER = "MODEL_VARIANT_MOLD_TRANSFER";
    private static final String STATUS_ACTIVE = "active";
    private static final String STATUS_VOID = "void";

    private final ProductRepository productRepository;
    private final TimelineDefinitionProvider timelineDefinitionProvider;
    private final ProjectMoldTransferExpressRepository repository;
    private final OperationLogService operationLogService;

    @Override
    public MoldTransferExpressVO get(Long projectId, String nodeKey) {
        Product product = getProductOrThrow(projectId);
        requireMoldTransferNode(product, nodeKey);
        return MoldTransferExpressVO.from(findActive(projectId, nodeKey));
    }

    @Override
    public MoldTransferExpressVO getSnapshot(Long projectId, String nodeKey) {
        return MoldTransferExpressVO.from(findActive(projectId, nodeKey));
    }

    @Override
    @Transactional
    public MoldTransferExpressVO save(Long projectId, String nodeKey, MoldTransferExpressSaveDTO dto, HttpServletRequest request) {
        Product product = getProductOrThrow(projectId);
        requireMoldTransferNode(product, nodeKey);
        if (dto == null || !StringUtils.hasText(dto.getTrackingNo())) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "快递单号不能为空");
        }
        ProjectMoldTransferExpress entity = findActive(projectId, nodeKey);
        LocalDateTime now = LocalDateTime.now();
        String operator = currentUserName();
        boolean created = entity == null;
        if (created) {
            entity = new ProjectMoldTransferExpress();
            entity.setProjectId(projectId);
            entity.setTimelineNodeKey(nodeKey);
            fillCreateAudit(entity, now, operator);
        } else {
            fillUpdateAudit(entity, operator);
        }
        entity.setTrackingNo(dto.getTrackingNo().trim());
        entity.setShippedAt(dto.getShippedAt());
        entity.setStatus(STATUS_ACTIVE);
        if (created) {
            repository.insert(entity);
        } else {
            repository.updateById(entity);
        }
        writeLog(product, OperationActionConstants.MOLD_TRANSFER_EXPRESS_SAVE,
            "{\"action\":\"save\",\"type\":\"mold_transfer_tracking_no\"}", request);
        return MoldTransferExpressVO.from(entity);
    }

    @Override
    @Transactional
    public void voidExpress(Long projectId, String nodeKey, HttpServletRequest request) {
        Product product = getProductOrThrow(projectId);
        requireMoldTransferNode(product, nodeKey);
        ProjectMoldTransferExpress entity = findActive(projectId, nodeKey);
        if (entity == null) {
            return;
        }
        entity.setStatus(STATUS_VOID);
        entity.setDeletedFlag(1);
        fillUpdateAudit(entity, currentUserName());
        repository.updateById(entity);
        writeLog(product, OperationActionConstants.MOLD_TRANSFER_EXPRESS_VOID,
            "{\"action\":\"void\",\"type\":\"mold_transfer_tracking_no\"}", request);
    }

    @Override
    public boolean hasActiveTracking(Long projectId, String nodeKey) {
        ProjectMoldTransferExpress entity = findActive(projectId, nodeKey);
        return entity != null && StringUtils.hasText(entity.getTrackingNo());
    }

    private Product getProductOrThrow(Long projectId) {
        Product product = productRepository.selectById(projectId);
        if (product == null || Integer.valueOf(1).equals(product.getDeletedFlag())) {
            throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "项目不存在");
        }
        return product;
    }

    private void requireMoldTransferNode(Product product, String nodeKey) {
        if (!PRODUCT_LINE_MOLD_TRANSFER.equals(nodeKey) && !MODEL_VARIANT_MOLD_TRANSFER.equals(nodeKey)) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "只有运模节点可以填写快递单号");
        }
        TimelineNodeDefinition definition = timelineDefinitionProvider.getDefinitionByCode(product, nodeKey);
        boolean expectedType = (TimelineNodeConstants.PRODUCT_TYPE_PRODUCT_LINE.equals(product.getProductType()) && PRODUCT_LINE_MOLD_TRANSFER.equals(definition.nodeCode()))
            || (TimelineNodeConstants.PRODUCT_TYPE_MODEL_VARIANT.equals(product.getProductType()) && MODEL_VARIANT_MOLD_TRANSFER.equals(definition.nodeCode()));
        if (!expectedType) {
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, "运模节点与项目类型不匹配");
        }
    }

    private ProjectMoldTransferExpress findActive(Long projectId, String nodeKey) {
        return repository.selectOne(new LambdaQueryWrapper<ProjectMoldTransferExpress>()
            .eq(ProjectMoldTransferExpress::getProjectId, projectId)
            .eq(ProjectMoldTransferExpress::getTimelineNodeKey, nodeKey)
            .eq(ProjectMoldTransferExpress::getDeletedFlag, 0)
            .last("limit 1"));
    }

    private void fillCreateAudit(com.yuewei.plm.repository.entity.BaseEntity entity, LocalDateTime now, String operator) {
        entity.setCreatedAt(now);
        entity.setCreatedBy(operator);
        entity.setUpdatedAt(now);
        entity.setUpdatedBy(operator);
        entity.setDeletedFlag(0);
    }

    private void fillUpdateAudit(com.yuewei.plm.repository.entity.BaseEntity entity, String operator) {
        entity.setUpdatedAt(LocalDateTime.now());
        entity.setUpdatedBy(operator);
    }

    private String currentUserName() {
        return CurrentUserContext.get()
            .map(CurrentUser::displayName)
            .filter(StringUtils::hasText)
            .orElse("system");
    }

    private void writeLog(Product product, String action, String detailJson, HttpServletRequest request) {
        operationLogService.logSuccess(OperationLogCreateCommand.builder()
            .action(action)
            .businessType("PRODUCT")
            .businessId(String.valueOf(product.getProductId()))
            .businessCode(product.getProductCode())
            .businessName(product.getProductName())
            .detailJson(detailJson)
            .request(request)
            .build());
    }
}
