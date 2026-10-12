package com.yuewei.plm.module.project.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.yuewei.plm.repository.entity.BaseEntity;
import java.time.LocalDateTime;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@TableName("plm_project_mold_transfer_express")
@EqualsAndHashCode(callSuper = true)
public class ProjectMoldTransferExpress extends BaseEntity {
    @TableId(value = "mold_transfer_express_id", type = IdType.AUTO)
    private Long moldTransferExpressId;
    private Long projectId;
    private String timelineNodeKey;
    private String carrierCode;
    private String carrierName;
    private String trackingNo;
    private String senderName;
    private String senderPhone;
    private String receiverName;
    private String receiverPhone;
    private String shipFrom;
    private String shipTo;
    private LocalDateTime shippedAt;
    private String latestStatus;
    private String latestStatusText;
    private LocalDateTime latestCheckpointAt;
    private LocalDateTime lastQueryAt;
    private String queryStatus;
    private String queryErrorMessage;
    private String rawTraceJson;
    private String status;
    private String remark;
}
