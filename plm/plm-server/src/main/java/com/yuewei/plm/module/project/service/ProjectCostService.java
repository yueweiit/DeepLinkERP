package com.yuewei.plm.module.project.service;

import com.yuewei.plm.module.project.dto.ProjectCostItemCreateDTO;
import com.yuewei.plm.module.project.dto.ProjectCostItemUpdateDTO;
import com.yuewei.plm.module.project.vo.ProjectCostItemVO;
import com.yuewei.plm.module.project.vo.ProjectCostSummaryVO;
import jakarta.servlet.http.HttpServletRequest;
import java.util.List;

public interface ProjectCostService {
    ProjectCostSummaryVO getSummary(Long projectId);

    List<ProjectCostItemVO> listItems(Long projectId);

    ProjectCostItemVO createItem(Long projectId, ProjectCostItemCreateDTO dto, HttpServletRequest request);

    ProjectCostItemVO updateItem(Long projectId, Long costItemId, ProjectCostItemUpdateDTO dto, HttpServletRequest request);

    ProjectCostItemVO confirmItem(Long projectId, Long costItemId, HttpServletRequest request);

    ProjectCostItemVO voidItem(Long projectId, Long costItemId, HttpServletRequest request);
}
