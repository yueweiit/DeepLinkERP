package com.yuewei.plm.module.process.controller;

import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.process.dto.ProcessRouteSaveDTO;
import com.yuewei.plm.module.process.service.ProcessRouteService;
import com.yuewei.plm.module.process.service.ProcessRouteTemplateService;
import com.yuewei.plm.module.process.vo.ProcessRouteTemplateVO;
import com.yuewei.plm.module.process.vo.ProcessRouteVO;
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
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@Validated
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/v1")
public class ProcessRouteController {

    private final ProcessRouteService processRouteService;
    private final ProcessRouteTemplateService processRouteTemplateService;

    @GetMapping("/process-route-templates")
    public ResponseVO<List<ProcessRouteTemplateVO>> listTemplates(@RequestParam(required = false) String productCode,
                                                                  @RequestParam(required = false) Boolean onlyDefault,
                                                                  HttpServletRequest request) {
        return ResponseVO.success(
            processRouteTemplateService.listTemplates(productCode, onlyDefault),
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }

    @GetMapping("/projects/{projectId}/process-routes")
    public ResponseVO<List<ProcessRouteVO>> listByProject(@PathVariable Long projectId, HttpServletRequest request) {
        return ResponseVO.success(processRouteService.listByProject(projectId), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @GetMapping("/process-routes/{processId}")
    public ResponseVO<ProcessRouteVO> detail(@PathVariable Long processId, HttpServletRequest request) {
        return ResponseVO.success(processRouteService.getById(processId), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/projects/{projectId}/process-routes")
    public ResponseVO<ProcessRouteVO> create(@PathVariable Long projectId,
                                             @Valid @RequestBody ProcessRouteSaveDTO dto,
                                             HttpServletRequest request) {
        return ResponseVO.success(processRouteService.create(projectId, dto, request), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PutMapping("/process-routes/{processId}")
    public ResponseVO<ProcessRouteVO> update(@PathVariable Long processId,
                                             @Valid @RequestBody ProcessRouteSaveDTO dto,
                                             HttpServletRequest request) {
        return ResponseVO.success(processRouteService.update(processId, dto, request), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @DeleteMapping("/process-routes/{processId}")
    public ResponseVO<Void> deleteVersion(@PathVariable Long processId, HttpServletRequest request) {
        processRouteService.deleteVersion(processId, request);
        return ResponseVO.success(null, RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/process-routes/{processId}/freeze")
    public ResponseVO<ProcessRouteVO> freeze(@PathVariable Long processId, HttpServletRequest request) {
        return ResponseVO.success(processRouteService.freeze(processId, request), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }
}
