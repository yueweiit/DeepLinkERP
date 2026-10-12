package com.yuewei.plm.module.process.vo;

import java.util.List;
import java.util.Map;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ProcessCenterSnapshotVO {
    private List<ProcessMetricCardVO> metrics;
    private List<ProcessRouteListItemVO> routes;
    private Map<Long, ProcessRouteDetailVO> routeDetails;
    private List<Object> templates;
}
