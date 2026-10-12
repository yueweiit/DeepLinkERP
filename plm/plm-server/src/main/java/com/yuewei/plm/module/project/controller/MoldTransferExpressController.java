package com.yuewei.plm.module.project.controller;

import com.yuewei.plm.common.constant.ApiConstants;
import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.project.dto.MoldTransferExpressSaveDTO;
import com.yuewei.plm.module.project.service.MoldTransferExpressService;
import com.yuewei.plm.module.project.vo.MoldTransferExpressVO;
import jakarta.servlet.http.HttpServletRequest;
import java.time.OffsetDateTime;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
@RequestMapping(ApiConstants.API_V1_PREFIX + "/projects")
public class MoldTransferExpressController {

    private final MoldTransferExpressService moldTransferExpressService;

    @GetMapping("/{projectId}/timeline/{nodeKey}/mold-transfer/express")
    public ResponseVO<MoldTransferExpressVO> get(@PathVariable Long projectId,
                                                 @PathVariable String nodeKey,
                                                 HttpServletRequest request) {
        return ResponseVO.success(
            moldTransferExpressService.get(projectId, nodeKey),
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }

    @PutMapping("/{projectId}/timeline/{nodeKey}/mold-transfer/express")
    public ResponseVO<MoldTransferExpressVO> save(@PathVariable Long projectId,
                                                  @PathVariable String nodeKey,
                                                  @RequestBody MoldTransferExpressSaveDTO dto,
                                                  HttpServletRequest request) {
        return ResponseVO.success(
            moldTransferExpressService.save(projectId, nodeKey, dto, request),
            RequestIdUtil.getRequestId(request),
            OffsetDateTime.now()
        );
    }

    @DeleteMapping("/{projectId}/timeline/{nodeKey}/mold-transfer/express")
    public ResponseVO<Void> voidExpress(@PathVariable Long projectId,
                                        @PathVariable String nodeKey,
                                        HttpServletRequest request) {
        moldTransferExpressService.voidExpress(projectId, nodeKey, request);
        return ResponseVO.success(RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }
}
