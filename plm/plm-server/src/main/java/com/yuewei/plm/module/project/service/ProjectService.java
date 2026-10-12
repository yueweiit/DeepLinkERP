package com.yuewei.plm.module.project.service;

import com.yuewei.plm.common.vo.PageVO;
import com.yuewei.plm.module.project.dto.ProjectQueryDTO;
import com.yuewei.plm.module.project.vo.ProjectDetailVO;
import com.yuewei.plm.module.project.vo.ProjectSummaryVO;

public interface ProjectService {

    PageVO<ProjectSummaryVO> pageInProgress(ProjectQueryDTO queryDTO);

    PageVO<ProjectSummaryVO> page(ProjectQueryDTO queryDTO);

    ProjectDetailVO getDetail(Long projectId);

    ProjectSummaryVO getSummary(Long projectId);
}
