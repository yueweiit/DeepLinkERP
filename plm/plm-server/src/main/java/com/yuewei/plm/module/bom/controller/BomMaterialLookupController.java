package com.yuewei.plm.module.bom.controller;

import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.bom.service.BomMaterialLookup;
import com.yuewei.plm.module.bom.vo.BomMaterialLookupVO;
import jakarta.servlet.http.HttpServletRequest;
import java.time.OffsetDateTime;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
@RequestMapping("/api/v1")
public class BomMaterialLookupController {
    private final BomMaterialLookup materialLookup;

    @GetMapping("/inventories/material-lookup")
    public ResponseVO<BomMaterialLookupVO> lookup(@RequestParam String inventoryCode, HttpServletRequest request) {
        String code = inventoryCode == null ? "" : inventoryCode.trim();
        BomMaterialLookupVO data = code.isBlank()
            ? BomMaterialLookupVO.unmatched(code)
            : materialLookup.findByCode(code)
                .map(BomMaterialLookupVO::matched)
                .orElseGet(() -> BomMaterialLookupVO.unmatched(code));
        return ResponseVO.success(data, RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }
}
