package com.yuewei.plm.module.bom.controller;

import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.common.vo.PageVO;
import com.yuewei.plm.module.bom.dto.BomLedgerQueryDTO;
import com.yuewei.plm.module.bom.vo.BomProductRowVO;
import com.yuewei.plm.module.bom.service.impl.JdbcBomLedgerPageService;
import com.yuewei.plm.module.bom.service.BomLedgerService;
import com.yuewei.plm.module.bom.vo.BomLedgerRowVO;
import com.yuewei.plm.module.bom.vo.BomSkuRowVO;
import com.yuewei.plm.module.bom.vo.BomSummaryVO;
import com.yuewei.plm.module.bom.vo.ProductBomWorkbenchVO;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import java.time.OffsetDateTime;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
@RequestMapping("/api/v1")
public class BomLedgerController {
    private final BomLedgerService ledgerService;
    private final JdbcBomLedgerPageService pageService;

    @GetMapping("/bom-ledger/products")
    public ResponseVO<PageVO<BomProductRowVO>> products(@Valid BomLedgerQueryDTO query, HttpServletRequest request) {
        return ResponseVO.success(pageService.products(query), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @GetMapping("/bom-ledger/products/{productId}/boms")
    public ResponseVO<PageVO<BomLedgerRowVO>> productBoms(@PathVariable Long productId, @Valid BomLedgerQueryDTO query, HttpServletRequest request) {
        return ResponseVO.success(pageService.boms(productId, query), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @GetMapping("/bom-ledger")
    public ResponseVO<List<BomLedgerRowVO>> list(HttpServletRequest request) {
        return ResponseVO.success(ledgerService.listFormal(), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @GetMapping("/boms/{bomId}/workbench")
    public ResponseVO<ProductBomWorkbenchVO> detail(@PathVariable Long bomId, HttpServletRequest request) {
        return ResponseVO.success(ledgerService.getWorkbench(bomId), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @GetMapping("/boms/{bomId}/skus")
    public ResponseVO<List<BomSkuRowVO>> skus(@PathVariable Long bomId, HttpServletRequest request) {
        return ResponseVO.success(ledgerService.listSkus(bomId), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @GetMapping("/process-routes/{routeId}/skus")
    public ResponseVO<List<BomSkuRowVO>> routeSkus(@PathVariable Long routeId, HttpServletRequest request) {
        return ResponseVO.success(ledgerService.listSkusForRoute(routeId), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @GetMapping("/products/{productId}/bom-summary")
    public ResponseVO<BomSummaryVO> summary(@PathVariable Long productId, HttpServletRequest request) {
        return ResponseVO.success(ledgerService.getSummary(productId), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }
}
