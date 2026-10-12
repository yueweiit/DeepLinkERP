package com.yuewei.plm.module.importexport.service;

import com.yuewei.plm.module.importexport.vo.ImportBatchVO;
import com.yuewei.plm.module.importexport.vo.ImportErrorVO;
import com.yuewei.plm.module.importexport.vo.ImportPreviewVO;
import jakarta.servlet.http.HttpServletRequest;
import java.util.List;
import org.springframework.web.multipart.MultipartFile;

public interface MasterDataImportExportService {

    byte[] template(String objectType);

    ImportPreviewVO preview(String objectType, MultipartFile file);

    ImportPreviewVO commit(String importToken, HttpServletRequest request);

    List<ImportErrorVO> errors(String importToken);

    byte[] export(String objectType, String keyword, String status, boolean full, HttpServletRequest request);

    List<ImportBatchVO> batches(String objectType);

    ImportBatchVO batch(Long importBatchId);
}
