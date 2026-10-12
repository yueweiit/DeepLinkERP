package com.yuewei.plm.module.auth.vo;

import com.yuewei.plm.common.security.CurrentUser;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class CurrentUserVO {

    private Long userId;
    private String username;
    private String displayName;
    private boolean allPermissions;
    private java.util.List<String> permissions;
    private String roleCode;
    private String departmentName;

    public static CurrentUserVO from(CurrentUser currentUser) {
        return CurrentUserVO.builder()
            .userId(currentUser.userId())
            .username(currentUser.username())
            .displayName(currentUser.displayName())
            .allPermissions(currentUser.allPermissions())
            .build();
    }
}
