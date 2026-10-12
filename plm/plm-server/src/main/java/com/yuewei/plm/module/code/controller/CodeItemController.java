package com.yuewei.plm.module.code.controller;

import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.PageVO;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.code.dto.CodeItemQueryDTO;
import com.yuewei.plm.module.code.dto.CodeItemSaveDTO;
import com.yuewei.plm.module.code.service.CodeItemService;
import com.yuewei.plm.module.code.service.CodeItemImportService;
import com.yuewei.plm.module.code.vo.CodeImportPreviewVO;
import com.yuewei.plm.module.code.vo.CodeItemVO;
import com.yuewei.plm.module.code.dto.PhoneModelReviewQueryDTO;
import com.yuewei.plm.module.code.vo.PhoneModelReviewVO;
import com.yuewei.plm.module.code.service.PhoneModelReviewService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import java.time.OffsetDateTime;
import lombok.RequiredArgsConstructor;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.http.MediaType;
import org.springframework.web.multipart.MultipartFile;

@Validated
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/v1/code-items")
public class CodeItemController {
    private final CodeItemService service;
    private final CodeItemImportService importService;
    private final PhoneModelReviewService reviewService;

    @GetMapping("/phone-model-review")
    public ResponseVO<PageVO<PhoneModelReviewVO>> review(@Valid PhoneModelReviewQueryDTO query, HttpServletRequest request) {
        return ResponseVO.success(reviewService.page(query), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @GetMapping
    public ResponseVO<PageVO<CodeItemVO>> page(@Valid CodeItemQueryDTO query, HttpServletRequest request) {
        return ResponseVO.success(service.page(query), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping
    public ResponseVO<CodeItemVO> create(@Valid @RequestBody CodeItemSaveDTO dto, HttpServletRequest request) {
        return ResponseVO.success(service.create(dto), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PutMapping("/{id}")
    public ResponseVO<CodeItemVO> update(@PathVariable Long id, @Valid @RequestBody CodeItemSaveDTO dto,
        HttpServletRequest request) {
        return ResponseVO.success(service.update(id, dto), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/{id}/enable")
    public ResponseVO<CodeItemVO> enable(@PathVariable Long id, HttpServletRequest request) {
        return ResponseVO.success(service.changeStatus(id, "enabled"), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/{id}/disable")
    public ResponseVO<CodeItemVO> disable(@PathVariable Long id, HttpServletRequest request) {
        return ResponseVO.success(service.changeStatus(id, "disabled"), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping(value = "/import/preview", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseVO<CodeImportPreviewVO> preview(@RequestParam("file") MultipartFile file,
        HttpServletRequest request) throws java.io.IOException {
        return ResponseVO.success(importService.preview(file.getOriginalFilename(), file.getBytes()),
            RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/import/{token}/commit")
    public ResponseVO<CodeImportPreviewVO> commit(@PathVariable String token, HttpServletRequest request) {
        return ResponseVO.success(importService.commit(token), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }
}
