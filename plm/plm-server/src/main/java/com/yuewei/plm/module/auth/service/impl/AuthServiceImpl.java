package com.yuewei.plm.module.auth.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.common.security.CurrentUserContext;
import com.yuewei.plm.module.auth.dto.LoginDTO;
import com.yuewei.plm.module.auth.service.AuthService;
import com.yuewei.plm.module.auth.service.TokenSessionService;
import com.yuewei.plm.module.auth.vo.CurrentUserVO;
import com.yuewei.plm.module.auth.vo.LoginVO;
import com.yuewei.plm.module.operationlog.constant.OperationActionConstants;
import com.yuewei.plm.module.operationlog.service.OperationLogCreateCommand;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.user.entity.SysUser;
import com.yuewei.plm.module.user.repository.SysUserRepository;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

@Service
@RequiredArgsConstructor
public class AuthServiceImpl implements AuthService {

    private static final String LOGIN_ERROR_MESSAGE = "账号或密码错误";
    private static final String BEARER_PREFIX = "Bearer ";
    private final SysUserRepository sysUserRepository;
    private final TokenSessionService tokenSessionService;
    private final OperationLogService operationLogService;
    private final PasswordEncoder passwordEncoder;
    @org.springframework.beans.factory.annotation.Autowired
    private com.yuewei.plm.module.pilot.PilotAccessService pilotAccess;

    @Override
    public LoginVO login(LoginDTO loginDTO, HttpServletRequest request) {
        SysUser user = sysUserRepository.selectOne(new LambdaQueryWrapper<SysUser>()
            .eq(SysUser::getUsername, loginDTO.getUsername())
            .last("limit 1"));
        if (!canLogin(user) || !passwordEncoder.matches(loginDTO.getPassword(), user.getPasswordHash())) {
            throw new BusinessException(ErrorCodeConstants.UNAUTHORIZED, LOGIN_ERROR_MESSAGE);
        }
        CurrentUser currentUser = new CurrentUser(
            user.getUserId(),
            user.getUsername(),
            user.getDisplayName(),
            Boolean.TRUE.equals(user.getAllPermissions())
        );
        String token = tokenSessionService.createSession(currentUser);
        CurrentUserContext.set(currentUser);
        try {
            operationLogService.logSuccess(OperationLogCreateCommand.builder()
                .action(OperationActionConstants.AUTH_LOGIN)
                .businessType("AUTH")
                .businessId(String.valueOf(user.getUserId()))
                .businessCode(user.getUsername())
                .businessName(user.getDisplayName())
                .request(request)
                .build());
        } finally {
            CurrentUserContext.clear();
        }
        return LoginVO.builder()
            .token(token)
            .tokenType("Bearer")
            .expiresInSeconds(tokenSessionService.getExpiresInSeconds())
            .user(pilotAccess==null?CurrentUserVO.from(currentUser):pilotAccess.userView(currentUser))
            .build();
    }

    @Override
    public CurrentUserVO profile() {
        CurrentUser currentUser = CurrentUserContext.get()
            .orElseThrow(() -> new BusinessException(ErrorCodeConstants.UNAUTHORIZED, "未登录或登录已失效"));
        return pilotAccess==null?CurrentUserVO.from(currentUser):pilotAccess.userView(currentUser);
    }

    @Override
    public void logout(String authorization, HttpServletRequest request) {
        String token = parseBearerToken(authorization);
        operationLogService.logSuccess(OperationLogCreateCommand.builder()
            .action(OperationActionConstants.AUTH_LOGOUT)
            .businessType("AUTH")
            .request(request)
            .build());
        tokenSessionService.invalidate(token);
    }

    private boolean canLogin(SysUser user) {
        return user != null
            && !Integer.valueOf(1).equals(user.getDeletedFlag())
            && "active".equals(user.getStatus());
    }

    private String parseBearerToken(String authorization) {
        if (!StringUtils.hasText(authorization) || !authorization.startsWith(BEARER_PREFIX)) {
            throw new BusinessException(ErrorCodeConstants.UNAUTHORIZED, "未登录或登录已失效");
        }
        return authorization.substring(BEARER_PREFIX.length());
    }

}
