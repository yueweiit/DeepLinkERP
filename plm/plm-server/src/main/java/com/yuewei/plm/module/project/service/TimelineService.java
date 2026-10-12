package com.yuewei.plm.module.project.service;

import com.yuewei.plm.module.project.vo.TimelineDetailVO;

public interface TimelineService {

    TimelineDetailVO getTimeline(Long projectId);
}
