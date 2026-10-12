package com.yuewei.plm.module.operationlog.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.common.security.CurrentUserContext;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.PageVO;
import com.yuewei.plm.module.operationlog.dto.OperationLogQueryDTO;
import com.yuewei.plm.module.operationlog.entity.OperationLog;
import com.yuewei.plm.module.operationlog.repository.OperationLogRepository;
import com.yuewei.plm.module.operationlog.service.OperationLogCreateCommand;
import com.yuewei.plm.module.operationlog.service.OperationLogDetails;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.operationlog.vo.OperationLogVO;
import java.time.LocalDateTime;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.util.StringUtils;

@Service
@RequiredArgsConstructor
public class OperationLogServiceImpl implements OperationLogService {

    private final OperationLogRepository operationLogRepository;

    @Override
    @Transactional(propagation = Propagation.NOT_SUPPORTED)
    public Long logSuccess(OperationLogCreateCommand command) {
        // Legacy best-effort calls stay compatible; security-sensitive changes use logRequired.
        try {
            return persist(command, CurrentUserContext.get().orElse(null));
        } catch (RuntimeException ignored) {
            return null;
        }
    }

    @Override
    @Transactional(propagation = Propagation.MANDATORY)
    public Long logRequired(OperationLogCreateCommand command, CurrentUser actor) {
        if (actor == null || actor.userId() == null || actor.userId() < 1 || !StringUtils.hasText(actor.username()))
            throw new BusinessException(40101, "审计需要真实登录账号");
        return persist(command, actor);
    }

    private Long persist(OperationLogCreateCommand command, CurrentUser currentUser) {
        // One construction/write policy for both transaction guarantees, never a client-supplied actor.
        String operatorName = currentUser == null ? null : currentUser.displayName();
        OperationLog log = new OperationLog();
        log.setRequestId(RequestIdUtil.getRequestId(command.getRequest()));
        log.setOperatorUserId(currentUser == null ? null : currentUser.userId());
        log.setOperatorUserName(operatorName);
        log.setAction(command.getAction());
        log.setBusinessType(command.getBusinessType());
        log.setBusinessId(command.getBusinessId());
        log.setBusinessCode(command.getBusinessCode());
        log.setBusinessName(command.getBusinessName());
        log.setResult("success");
        log.setRequestMethod(command.getRequest() == null ? null : command.getRequest().getMethod());
        log.setRequestUri(command.getRequest() == null ? null : command.getRequest().getRequestURI());
        log.setClientIp(command.getRequest() == null ? null : command.getRequest().getRemoteAddr());
        log.setUserAgent(command.getRequest() == null ? null : command.getRequest().getHeader("User-Agent"));
        log.setDetailJson(OperationLogDetails.sanitize(command.getDetailJson()));
        LocalDateTime savedAt = LocalDateTime.now();
        log.setCreatedAt(savedAt);
        log.setCreatedBy(StringUtils.hasText(operatorName) ? operatorName : "system");
        log.setUpdatedAt(savedAt);
        log.setUpdatedBy(StringUtils.hasText(operatorName) ? operatorName : "system");
        log.setDeletedFlag(0);
        if (operationLogRepository.insert(log) != 1 || log.getLogId() == null)
            throw new IllegalStateException("操作日志写入失败");
        return log.getLogId();
    }

    @Override
    public PageVO<OperationLogVO> page(OperationLogQueryDTO queryDTO) {
        if (!queryDTO.isDateRangeValid()) throw new BusinessException(40001, "日志开始时间不得晚于结束时间");
        LambdaQueryWrapper<OperationLog> queryWrapper = new LambdaQueryWrapper<OperationLog>()
            .eq(StringUtils.hasText(queryDTO.getRequestId()), OperationLog::getRequestId, queryDTO.getRequestId())
            .eq(queryDTO.getOperatorUserId() != null, OperationLog::getOperatorUserId, queryDTO.getOperatorUserId())
            .eq(StringUtils.hasText(queryDTO.getAction()), OperationLog::getAction, queryDTO.getAction())
            .eq(StringUtils.hasText(queryDTO.getBusinessType()), OperationLog::getBusinessType, queryDTO.getBusinessType())
            .eq(StringUtils.hasText(queryDTO.getBusinessId()), OperationLog::getBusinessId, queryDTO.getBusinessId())
            .ge(queryDTO.getCreatedFrom() != null, OperationLog::getCreatedAt, queryDTO.getCreatedFrom())
            .le(queryDTO.getCreatedTo() != null, OperationLog::getCreatedAt, queryDTO.getCreatedTo())
            .orderByDesc(OperationLog::getCreatedAt, OperationLog::getLogId);
        IPage<OperationLog> page = operationLogRepository.selectPage(
            new Page<>(queryDTO.getPage(), queryDTO.getSize()),
            queryWrapper
        );
        return PageVO.<OperationLogVO>builder()
            .content(page.getRecords().stream().map(OperationLogVO::from).toList())
            .page(page.getCurrent())
            .size(page.getSize())
            .totalElements(page.getTotal())
            .totalPages(page.getPages())
            .build();
    }
}
