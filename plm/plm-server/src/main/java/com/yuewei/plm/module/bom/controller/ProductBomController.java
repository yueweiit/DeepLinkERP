package com.yuewei.plm.module.bom.controller;

import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.bom.dto.ProductBomCreateDTO;
import com.yuewei.plm.module.bom.dto.BomInheritanceDTO;
import com.yuewei.plm.module.bom.dto.BomCopyVersionDTO;
import com.yuewei.plm.module.bom.dto.BomRouteSaveDTO;
import com.yuewei.plm.module.bom.dto.TestBomSaveDTO;
import com.yuewei.plm.module.bom.dto.ProductBomItemDTO;
import com.yuewei.plm.module.bom.dto.ProductBomUpdateDTO;
import com.yuewei.plm.module.bom.service.ProductBomService;
import com.yuewei.plm.module.bom.service.impl.HistoricalBomMergeService;
import com.yuewei.plm.module.bom.service.impl.HistoricalBomImportService;
import com.yuewei.plm.module.bom.service.BomImportService;
import com.yuewei.plm.module.bom.service.BomInheritanceService;
import com.yuewei.plm.module.bom.service.ProductBomWorkflowService;
import com.yuewei.plm.module.bom.entity.ProductBom;
import com.yuewei.plm.module.bom.entity.ProductBomCostSnapshot;
import com.yuewei.plm.module.bom.entity.ProductBomImportBatch;
import com.yuewei.plm.module.bom.vo.BomImportPreviewVO;
import com.yuewei.plm.module.bom.vo.BomHistoryMergeResultVO;
import com.yuewei.plm.module.bom.vo.ProductBomVO;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import java.time.OffsetDateTime;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;

@Validated
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/v1")
public class ProductBomController {

    private final ProductBomService productBomService;
    private final ProductBomWorkflowService workflowService;
    private final BomInheritanceService inheritanceService;
    private final BomImportService importService;
    private final HistoricalBomImportService historicalImportService;
    private final HistoricalBomMergeService historicalBomMergeService;

    @GetMapping("/projects/{projectId}/boms")
    public ResponseVO<List<ProductBomVO>> listByProject(@PathVariable Long projectId, HttpServletRequest request) {
        return ResponseVO.success(productBomService.listByProject(projectId), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @GetMapping("/boms/{bomId}")
    public ResponseVO<ProductBomVO> detail(@PathVariable Long bomId, HttpServletRequest request) {
        return ResponseVO.success(productBomService.getById(bomId), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/projects/{projectId}/boms")
    public ResponseVO<ProductBomVO> create(@PathVariable Long projectId,
                                           @Valid @RequestBody ProductBomCreateDTO dto,
                                           HttpServletRequest request) {
        return ResponseVO.success(productBomService.create(projectId, dto, request), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PutMapping("/boms/{bomId}")
    public ResponseVO<ProductBomVO> update(@PathVariable Long bomId,
                                           @Valid @RequestBody ProductBomUpdateDTO dto,
                                           HttpServletRequest request) {
        return ResponseVO.success(productBomService.update(bomId, dto, request), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/boms/{bomId}/items")
    public ResponseVO<ProductBomVO> addItem(@PathVariable Long bomId,
                                            @Valid @RequestBody ProductBomItemDTO dto,
                                            HttpServletRequest request) {
        return ResponseVO.success(productBomService.addItem(bomId, dto, request), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PutMapping("/boms/{bomId}/items/{itemId}")
    public ResponseVO<ProductBomVO> updateItem(@PathVariable Long bomId,
                                               @PathVariable Long itemId,
                                               @Valid @RequestBody ProductBomItemDTO dto,
                                               HttpServletRequest request) {
        return ResponseVO.success(productBomService.updateItem(bomId, itemId, dto, request), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @DeleteMapping("/boms/{bomId}/items/{itemId}")
    public ResponseVO<ProductBomVO> deleteItem(@PathVariable Long bomId,
                                               @PathVariable Long itemId,
                                               HttpServletRequest request) {
        return ResponseVO.success(productBomService.deleteItem(bomId, itemId, request), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @DeleteMapping("/boms/{bomId}")
    public ResponseVO<Void> deleteVersion(@PathVariable Long bomId, HttpServletRequest request) {
        productBomService.deleteVersion(bomId, request);
        return ResponseVO.success(null, RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/boms/{bomId}/freeze")
    public ResponseVO<ProductBom> freeze(@PathVariable Long bomId, HttpServletRequest request) {
        return ResponseVO.success(workflowService.freeze(bomId), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/boms/{bomId}/confirm-current-version")
    public ResponseVO<ProductBomVO> confirmCurrentVersion(@PathVariable Long bomId, HttpServletRequest request) {
        return ResponseVO.success(productBomService.confirmCurrentVersion(bomId, request),
            RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/boms/{bomId}/cancel-confirmation")
    public ResponseVO<ProductBomVO> cancelCurrentConfirmation(@PathVariable Long bomId, HttpServletRequest request) {
        return ResponseVO.success(productBomService.cancelCurrentConfirmation(bomId, request),
            RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PutMapping("/boms/{bomId}/routes")
    public ResponseVO<Void> saveRoutes(@PathVariable Long bomId,
                                       @Valid @RequestBody List<BomRouteSaveDTO> routes,
                                       HttpServletRequest request) {
        workflowService.saveRoutes(bomId, routes);
        return ResponseVO.success(null, RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/products/{productId}/test-bom")
    public ResponseVO<ProductBom> saveTestBom(@PathVariable Long productId,
                                              @Valid @RequestBody TestBomSaveDTO dto,
                                              HttpServletRequest request) {
        return ResponseVO.success(workflowService.saveTestBom(productId, dto),
            RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/products/{productId}/test-bom/confirm")
    public ResponseVO<ProductBom> confirmTestBom(@PathVariable Long productId, HttpServletRequest request) {
        return ResponseVO.success(workflowService.confirmTestBom(productId),
            RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/boms/{bomId}/costs/recalculate")
    public ResponseVO<List<ProductBomCostSnapshot>> recalculateCosts(
        @PathVariable Long bomId,
        @Valid @RequestBody List<BomRouteSaveDTO> costs,
        HttpServletRequest request
    ) {
        return ResponseVO.success(workflowService.recalculateCosts(bomId, costs),
            RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/boms/{bomId}/submit-review")
    public ResponseVO<ProductBom> submitReview(@PathVariable Long bomId, HttpServletRequest request) {
        return ResponseVO.success(workflowService.submitReview(bomId),
            RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/boms/{bomId}/publish")
    public ResponseVO<ProductBom> publish(@PathVariable Long bomId, HttpServletRequest request) {
        return ResponseVO.success(workflowService.publish(bomId),
            RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/boms/{bomId}/copy-version")
    public ResponseVO<ProductBom> copyVersion(@PathVariable Long bomId,
                                              @Valid @RequestBody BomCopyVersionDTO dto,
                                              HttpServletRequest request) {
        return ResponseVO.success(
            inheritanceService.copyVersion(bomId, dto.getVersionNo(), dto.getSelectedColors()),
            RequestIdUtil.getRequestId(request), OffsetDateTime.now()
        );
    }

    @PostMapping("/products/{productId}/boms/inherit")
    public ResponseVO<ProductBom> inherit(@PathVariable Long productId,
                                          @Valid @RequestBody BomInheritanceDTO dto,
                                          HttpServletRequest request) {
        return ResponseVO.success(inheritanceService.inherit(dto.getSourceBomId(), productId, dto.getSelectedColors()),
            RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping(value = "/products/{productId}/boms/import/preview", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseVO<BomImportPreviewVO> previewImport(
        @PathVariable Long productId,
        @RequestParam Long bomId,
        @RequestParam("file") MultipartFile file,
        HttpServletRequest request
    ) throws java.io.IOException {
        return ResponseVO.success(importService.preview(productId, bomId, file.getOriginalFilename(), file.getBytes()),
            RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/boms/import/{importToken}/commit")
    public ResponseVO<ProductBomImportBatch> commitImport(@PathVariable String importToken, HttpServletRequest request) {
        return ResponseVO.success(importService.commit(importToken),
            RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @GetMapping("/boms/import/template")
    public ResponseEntity<byte[]> downloadTemplate() {
        return xlsx("BOM-import-template.xlsx", importService.buildTemplate());
    }

    @GetMapping("/boms/import/{importToken}/errors")
    public ResponseEntity<byte[]> downloadErrors(@PathVariable String importToken) {
        return xlsx("BOM-import-errors.xlsx", importService.buildErrorReport(importService.getErrors(importToken)));
    }

    @PostMapping(value = "/boms/history/import/preview", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseVO<BomImportPreviewVO> previewHistoricalImport(@RequestParam("file") MultipartFile file,
        HttpServletRequest request) throws java.io.IOException {
        return ResponseVO.success(historicalImportService.preview(file.getOriginalFilename(), file.getBytes()),
            RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/boms/history/import/{importToken}/commit")
    public ResponseVO<ProductBomImportBatch> commitHistoricalImport(@PathVariable String importToken,
        HttpServletRequest request) {
        return ResponseVO.success(historicalImportService.commit(importToken),
            RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @GetMapping("/boms/history/import/template")
    public ResponseEntity<byte[]> downloadHistoricalTemplate() {
        return xlsx("historical-BOM-import-template.xlsx", historicalImportService.buildTemplate());
    }

    @GetMapping("/boms/history/merge/analysis")
    public ResponseVO<BomHistoryMergeResultVO> analyzeHistoricalBomMerge(
        @RequestParam(required = false) Long productId,
        HttpServletRequest request
    ) {
        return ResponseVO.success(historicalBomMergeService.analyze(productId),
            RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/boms/history/merge/auto")
    public ResponseVO<BomHistoryMergeResultVO> autoMergeHistoricalBoms(
        @RequestParam(required = false) Long productId,
        HttpServletRequest request
    ) {
        return ResponseVO.success(historicalBomMergeService.autoMerge(productId, request),
            RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    private ResponseEntity<byte[]> xlsx(String fileName, byte[] content) {
        return ResponseEntity.ok()
            .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"" + fileName + "\"")
            .contentType(MediaType.parseMediaType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
            .body(content);
    }
}
