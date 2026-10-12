package com.yuewei.plm.module.project.service;

import com.yuewei.plm.module.project.dto.MoldTransferExpressSaveDTO;
import com.yuewei.plm.module.project.vo.MoldTransferExpressVO;
import jakarta.servlet.http.HttpServletRequest;

public interface MoldTransferExpressService {
    MoldTransferExpressVO get(Long projectId, String nodeKey);

    MoldTransferExpressVO getSnapshot(Long projectId, String nodeKey);

    MoldTransferExpressVO save(Long projectId, String nodeKey, MoldTransferExpressSaveDTO dto, HttpServletRequest request);

    void voidExpress(Long projectId, String nodeKey, HttpServletRequest request);

    boolean hasActiveTracking(Long projectId, String nodeKey);
}
