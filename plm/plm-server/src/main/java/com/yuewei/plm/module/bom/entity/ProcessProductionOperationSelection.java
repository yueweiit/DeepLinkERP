package com.yuewei.plm.module.bom.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.yuewei.plm.repository.entity.BaseEntity;
import java.time.LocalDateTime;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@TableName("plm_process_production_operation_selection")
@EqualsAndHashCode(callSuper = true)
public class ProcessProductionOperationSelection extends BaseEntity {
    @TableId(value = "process_production_operation_selection_id", type = IdType.AUTO)
    private Long processProductionOperationSelectionId;
    private Long productId;
    private Long productBomRouteId;
    private Long processId;
    private Long operationProcessId;
    private String routeVersionNo;
    private String selectionBatchNo;
    private String status;
    private LocalDateTime confirmedAt;
    private String confirmedBy;
}
