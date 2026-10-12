package com.yuewei.plm.module.auth.vo;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class LoginVO {

    private String token;
    private String tokenType;
    private long expiresInSeconds;
    private CurrentUserVO user;
}
