package com.yuewei.plm.module.project.service;

import com.yuewei.plm.module.project.dto.TimelineActionDTO;
import com.yuewei.plm.module.project.vo.TimelineActionResultVO;
import jakarta.servlet.http.HttpServletRequest;

public interface TimelineActionService {

    TimelineActionResultVO confirm(Long projectId, String nodeKey, TimelineActionDTO dto, HttpServletRequest request);

    TimelineActionResultVO advance(Long projectId, String nodeKey, TimelineActionDTO dto, HttpServletRequest request);

    TimelineActionResultVO returnNode(Long projectId, String nodeKey, TimelineActionDTO dto, HttpServletRequest request);
}
