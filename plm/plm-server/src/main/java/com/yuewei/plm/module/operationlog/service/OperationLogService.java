package com.yuewei.plm.module.operationlog.service;

import com.yuewei.plm.common.vo.PageVO;
import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.module.operationlog.dto.OperationLogQueryDTO;
import com.yuewei.plm.module.operationlog.vo.OperationLogVO;

public interface OperationLogService {

    Long logSuccess(OperationLogCreateCommand command);

    /** Mandatory audit in the caller transaction, with its server-resolved actor snapshot. */
    Long logRequired(OperationLogCreateCommand command, CurrentUser actor);

    PageVO<OperationLogVO> page(OperationLogQueryDTO queryDTO);
}
