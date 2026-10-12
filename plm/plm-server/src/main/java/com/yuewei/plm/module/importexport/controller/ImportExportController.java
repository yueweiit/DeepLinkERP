package com.yuewei.plm.module.importexport.controller;

import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.importexport.service.MasterDataImportExportService;
import com.yuewei.plm.module.importexport.vo.ImportBatchVO;
import com.yuewei.plm.module.importexport.vo.ImportErrorVO;
import com.yuewei.plm.module.importexport.vo.ImportPreviewVO;
import jakarta.servlet.http.HttpServletRequest;
import java.nio.charset.StandardCharsets;
import java.time.OffsetDateTime;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequiredArgsConstructor
@RequestMapping("/api/v1/import-export")
public class ImportExportController {

    private final MasterDataImportExportService importExportService;

    @GetMapping("/templates/{objectType}")
    public ResponseEntity<byte[]> template(@PathVariable String objectType) {
        byte[] bytes = importExportService.template(objectType);
        return excel(bytes, objectType + "_import_template.xlsx");
    }

    @PostMapping("/{objectType}/preview")
    public ResponseVO<ImportPreviewVO> preview(@PathVariable String objectType,
                                               @RequestParam("file") MultipartFile file,
                                               HttpServletRequest request) {
        return ResponseVO.success(
            importExportService.preview(objectType, file),
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }

    @PostMapping("/{importToken}/commit")
    public ResponseVO<ImportPreviewVO> commit(@PathVariable String importToken, HttpServletRequest request) {
        return ResponseVO.success(
            importExportService.commit(importToken, request),
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }

    @GetMapping("/{importToken}/errors")
    public ResponseVO<List<ImportErrorVO>> errors(@PathVariable String importToken, HttpServletRequest request) {
        return ResponseVO.success(
            importExportService.errors(importToken),
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }

    @GetMapping("/{objectType}/export")
    public ResponseEntity<byte[]> export(@PathVariable String objectType,
                                         @RequestParam(required = false) String keyword,
                                         @RequestParam(required = false) String status,
                                         @RequestParam(defaultValue = "false") boolean full,
                                         HttpServletRequest request) {
        byte[] bytes = importExportService.export(objectType, keyword, status, full, request);
        return excel(bytes, objectType + "_export.xlsx");
    }

    @GetMapping("/batches")
    public ResponseVO<List<ImportBatchVO>> batches(@RequestParam(required = false) String objectType,
                                                   HttpServletRequest request) {
        return ResponseVO.success(
            importExportService.batches(objectType),
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }

    @GetMapping("/batches/{importBatchId}")
    public ResponseVO<ImportBatchVO> batch(@PathVariable Long importBatchId, HttpServletRequest request) {
        return ResponseVO.success(
            importExportService.batch(importBatchId),
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }

    private ResponseEntity<byte[]> excel(byte[] bytes, String fileName) {
        return ResponseEntity.ok()
            .header(HttpHeaders.CONTENT_DISPOSITION, ContentDisposition.attachment()
                .filename(fileName, StandardCharsets.UTF_8)
                .build()
                .toString())
            .contentType(MediaType.parseMediaType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
            .body(bytes);
    }
}
