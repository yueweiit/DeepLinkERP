package com.yuewei.plm.module.process.service;

import com.yuewei.plm.module.process.vo.ProcessCenterSnapshotVO;
import com.yuewei.plm.module.process.vo.ProcessRouteRelationVO;

public interface ProcessCenterService {
    ProcessCenterSnapshotVO snapshot();

    ProcessRouteRelationVO relations(Long processId);
}
