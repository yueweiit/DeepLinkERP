package com.yuewei.plm.module.auth.service.impl;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.module.auth.dto.LoginDTO;
import com.yuewei.plm.module.auth.vo.LoginVO;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.user.entity.SysUser;
import com.yuewei.plm.module.user.repository.SysUserRepository;
import jakarta.servlet.http.HttpServletRequest;
import org.junit.jupiter.api.Test;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;

class AuthServiceImplTest {

    @Test
    void loginWithCorrectPasswordReturnsTokenAndCurrentUser() {
        SysUserRepository userRepository = mock(SysUserRepository.class);
        InMemoryTokenSessionService tokenSessionService = new InMemoryTokenSessionService();
        OperationLogService operationLogService = mock(OperationLogService.class);
        BCryptPasswordEncoder passwordEncoder = new BCryptPasswordEncoder();
        AuthServiceImpl authService = new AuthServiceImpl(userRepository, tokenSessionService, operationLogService, passwordEncoder);
        SysUser user = activeUser(passwordEncoder.encode("initial-password"));
        when(userRepository.selectOne(any(LambdaQueryWrapper.class))).thenReturn(user);
        when(operationLogService.logSuccess(any())).thenReturn(10L);

        LoginVO loginVO = authService.login(new LoginDTO("engineer01", "initial-password"), mock(HttpServletRequest.class));

        assertThat(loginVO.getToken()).isNotBlank();
        assertThat(loginVO.getTokenType()).isEqualTo("Bearer");
        assertThat(loginVO.getExpiresInSeconds()).isEqualTo(28800L);
        assertThat(loginVO.getUser().getUserId()).isEqualTo(1L);
        assertThat(loginVO.getUser().getUsername()).isEqualTo("engineer01");
        assertThat(loginVO.getUser().isAllPermissions()).isTrue();
        verify(operationLogService).logSuccess(any());
    }

    @Test
    void loginWithWrongPasswordThrowsUnifiedAuthError() {
        SysUserRepository userRepository = mock(SysUserRepository.class);
        InMemoryTokenSessionService tokenSessionService = new InMemoryTokenSessionService();
        OperationLogService operationLogService = mock(OperationLogService.class);
        BCryptPasswordEncoder passwordEncoder = new BCryptPasswordEncoder();
        AuthServiceImpl authService = new AuthServiceImpl(userRepository, tokenSessionService, operationLogService, passwordEncoder);
        when(userRepository.selectOne(any(LambdaQueryWrapper.class))).thenReturn(activeUser(passwordEncoder.encode("right-password")));

        assertThatThrownBy(() -> authService.login(new LoginDTO("engineer01", "wrong-password"), mock(HttpServletRequest.class)))
            .isInstanceOf(BusinessException.class)
            .extracting("code")
            .isEqualTo(ErrorCodeConstants.UNAUTHORIZED);
    }

    private SysUser activeUser(String passwordHash) {
        SysUser user = new SysUser();
        user.setUserId(1L);
        user.setUsername("engineer01");
        user.setPasswordHash(passwordHash);
        user.setDisplayName("工程部用户一");
        user.setDepartmentName("工程部");
        user.setFormalFlag(1);
        user.setAllPermissions(true);
        user.setStatus("active");
        user.setDeletedFlag(0);
        return user;
    }
}
