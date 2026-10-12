package com.yuewei.plm.module.auth.controller;

import com.yuewei.plm.common.constant.ApiConstants;
import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.auth.dto.LoginDTO;
import com.yuewei.plm.module.auth.service.AuthService;
import com.yuewei.plm.module.auth.vo.CurrentUserVO;
import com.yuewei.plm.module.auth.vo.LoginVO;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import java.time.OffsetDateTime;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
@RequestMapping(ApiConstants.API_V1_PREFIX + "/auth")
public class AuthController {

    private final AuthService authService;

    @PostMapping("/login")
    public ResponseVO<LoginVO> login(@Valid @RequestBody LoginDTO loginDTO, HttpServletRequest request) {
        return ResponseVO.success(authService.login(loginDTO, request), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @GetMapping("/profile")
    public ResponseVO<CurrentUserVO> profile(HttpServletRequest request) {
        return ResponseVO.success(authService.profile(), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/logout")
    public ResponseVO<Void> logout(@RequestHeader("Authorization") String authorization, HttpServletRequest request) {
        authService.logout(authorization, request);
        return ResponseVO.success(RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }
}
