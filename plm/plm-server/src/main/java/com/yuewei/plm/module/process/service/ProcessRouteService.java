package com.yuewei.plm.module.process.service;

import com.yuewei.plm.module.process.dto.ProcessRouteSaveDTO;
import com.yuewei.plm.module.process.vo.ProcessRouteVO;
import jakarta.servlet.http.HttpServletRequest;
import java.util.List;

public interface ProcessRouteService {

    List<ProcessRouteVO> listByProject(Long projectId);

    ProcessRouteVO getById(Long processId);

    ProcessRouteVO create(Long projectId, ProcessRouteSaveDTO dto, HttpServletRequest request);

    ProcessRouteVO update(Long processId, ProcessRouteSaveDTO dto, HttpServletRequest request);

    void deleteVersion(Long processId, HttpServletRequest request);

    ProcessRouteVO freeze(Long processId, HttpServletRequest request);
}
