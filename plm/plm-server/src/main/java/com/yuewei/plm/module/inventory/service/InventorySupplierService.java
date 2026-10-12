package com.yuewei.plm.module.inventory.service;

import com.yuewei.plm.module.inventory.dto.SupplierSupplySideSaveDTO;
import com.yuewei.plm.module.inventory.vo.InventorySupplierCenterSnapshotVO;
import com.yuewei.plm.module.inventory.vo.InventorySupplierCenterSnapshotVO.SupplierDetail;
import jakarta.servlet.http.HttpServletRequest;

public interface InventorySupplierService {

    InventorySupplierCenterSnapshotVO snapshot();

    SupplierDetail create(SupplierSupplySideSaveDTO dto, HttpServletRequest request);

    SupplierDetail update(String supplierCode, SupplierSupplySideSaveDTO dto, HttpServletRequest request);
}
