package com.yuewei.plm.module.bom.vo;

import java.util.List;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class BomHistoryMergeResultVO {
    private Integer analyzedGroupCount;
    private Integer autoMergeableGroupCount;
    private Integer autoMergedGroupCount;
    private Integer archivedBomCount;
    private List<BomHistoryMergeCandidateVO> candidates;
    private List<BomHistoryMergeCandidateVO> mergedGroups;
}
