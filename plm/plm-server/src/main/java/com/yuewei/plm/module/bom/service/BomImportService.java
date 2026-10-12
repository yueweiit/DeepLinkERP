package com.yuewei.plm.module.bom.service;

import com.yuewei.plm.module.bom.entity.ProductBomImportBatch;
import com.yuewei.plm.module.bom.vo.BomImportErrorVO;
import com.yuewei.plm.module.bom.vo.BomImportPreviewVO;
import java.util.List;

public interface BomImportService {
    BomImportPreviewVO preview(Long productId, Long bomId, String fileName, byte[] content);
    ProductBomImportBatch commit(String importToken);
    List<BomImportErrorVO> getErrors(String importToken);
    byte[] buildErrorReport(List<BomImportErrorVO> errors);
    byte[] buildTemplate();
}
