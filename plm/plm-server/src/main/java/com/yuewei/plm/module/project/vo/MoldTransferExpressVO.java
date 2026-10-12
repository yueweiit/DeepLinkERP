package com.yuewei.plm.module.project.vo;

import com.yuewei.plm.module.project.entity.ProjectMoldTransferExpress;
import java.time.LocalDateTime;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class MoldTransferExpressVO {
    private Long moldTransferExpressId;
    private Long projectId;
    private String timelineNodeKey;
    private String trackingNo;
    private LocalDateTime shippedAt;
    private String status;

    public static MoldTransferExpressVO from(ProjectMoldTransferExpress entity) {
        if (entity == null) return null;
        return MoldTransferExpressVO.builder()
            .moldTransferExpressId(entity.getMoldTransferExpressId())
            .projectId(entity.getProjectId())
            .timelineNodeKey(entity.getTimelineNodeKey())
            .trackingNo(entity.getTrackingNo())
            .shippedAt(entity.getShippedAt())
            .status(entity.getStatus())
            .build();
    }
}
