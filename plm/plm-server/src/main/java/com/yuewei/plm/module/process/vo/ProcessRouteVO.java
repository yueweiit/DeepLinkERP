package com.yuewei.plm.module.process.vo;

import com.yuewei.plm.module.process.entity.ProcessEntity;
import java.time.LocalDateTime;
import java.util.List;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ProcessRouteVO {

    private Long processId;
    private Long productId;
    private String processCode;
    private String processName;
    private String processType;
    private String versionNo;
    private String status;
    private String routeTemplateCode;
    private String routeTemplateVersion;
    private String applicableModel;
    private String applicableColor;
    private String linkedBomVersionNo;
    private Boolean finalSelected;
    private LocalDateTime frozenAt;
    private String frozenBy;
    private String remark;
    private List<ProcessOperationVO> operations;

    public static ProcessRouteVO from(ProcessEntity route, List<ProcessOperationVO> operations) {
        return ProcessRouteVO.builder()
            .processId(route.getProcessId())
            .productId(route.getProductId())
            .processCode(route.getProcessCode())
            .processName(route.getProcessName())
            .processType(route.getProcessType())
            .versionNo(route.getVersionNo())
            .status(route.getStatus())
            .frozenAt(route.getFrozenAt())
            .frozenBy(route.getFrozenBy())
            .remark(route.getRemark())
            .operations(operations)
            .build();
    }
}
