package com.yuewei.plm.module.inventory.service;

import com.yuewei.plm.module.inventory.vo.InventoryCenterSnapshotVO;
import com.yuewei.plm.module.inventory.dto.InventoryCenterQueryDTO;
import com.yuewei.plm.common.vo.PageVO;
import java.util.List;

public interface InventoryCenterService {
    InventoryCenterSnapshotVO snapshot();
    PageVO<InventoryCenterSnapshotVO.InventoryListRow> page(InventoryCenterQueryDTO query);
    List<InventoryCenterSnapshotVO.InventoryTreeNode> groups();
}
