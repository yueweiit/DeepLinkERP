package com.yuewei.plm.module.process.service;

import com.yuewei.plm.module.process.dto.ProcessOperationMasterSaveDTO;
import com.yuewei.plm.module.process.vo.ProcessOperationMasterVO;
import java.util.List;

public interface ProcessOperationMasterService {

    List<ProcessOperationMasterVO> list(String keyword, String processCategory, String operationType, String status);

    ProcessOperationMasterVO create(ProcessOperationMasterSaveDTO dto);

    ProcessOperationMasterVO update(Long processId, ProcessOperationMasterSaveDTO dto);

    ProcessOperationMasterVO confirm(Long processId);

    ProcessOperationMasterVO archive(Long processId);
}
