package com.yuewei.plm.module.marketwatch;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.common.security.CurrentUserContext;
import com.yuewei.plm.module.collaboration.CollaborationService;
import com.yuewei.plm.module.marketwatch.MarketWatchTypes.Promote;
import com.yuewei.plm.module.marketwatch.MarketWatchTypes.UpdateItem;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.SimpleTransactionStatus;

class MarketWatchServiceTest {
    private MarketWatchClient client;
    private JdbcTemplate jdbc;
    private CollaborationService collaboration;
    private MarketWatchService service;

    @BeforeEach
    void setUp() {
        client = mock(MarketWatchClient.class);
        jdbc = mock(JdbcTemplate.class);
        collaboration = mock(CollaborationService.class);
        when(client.enabled()).thenReturn(true);
        service = new MarketWatchService(
            client,
            jdbc,
            new ObjectMapper(),
            collaboration,
            noOpTransactions()
        );
    }

    @AfterEach
    void clearActor() {
        CurrentUserContext.clear();
    }

    @Test
    void rejectsAnonymousAndDisabledAccessBeforeCallingPython() {
        assertThatThrownBy(service::summary)
            .isInstanceOfSatisfying(BusinessException.class,
                error -> assertThat(error.getCode()).isEqualTo(ErrorCodeConstants.UNAUTHORIZED));

        CurrentUserContext.set(new CurrentUser(7L, "reader", "只读用户", false));
        when(client.enabled()).thenReturn(false);
        assertThatThrownBy(service::summary)
            .isInstanceOfSatisfying(BusinessException.class,
                error -> assertThat(error.getCode()).isEqualTo(ErrorCodeConstants.RESOURCE_NOT_FOUND));
        verify(client, never()).summary();
    }

    @Test
    void onlyMarketAssignmentOrAdministratorCanMaintainItems() {
        UpdateItem update = new UpdateItem("sampled", "重点", null);
        CurrentUserContext.set(new CurrentUser(7L, "reader", "只读用户", false));
        doReturn(user("reader", "只读用户", false)).when(jdbc).queryForList(anyString(), (Object[]) any());
        when(jdbc.queryForObject(anyString(), any(Class.class), any())).thenReturn(0L);

        assertThatThrownBy(() -> service.update("phone", 9L, update))
            .isInstanceOfSatisfying(BusinessException.class,
                error -> assertThat(error.getCode()).isEqualTo(ErrorCodeConstants.FORBIDDEN));
        verify(client, never()).update(anyString(), anyLong(), any());

        CurrentUserContext.set(new CurrentUser(1L, "admin", "管理员", true));
        doReturn(user("admin", "管理员", true)).when(jdbc).queryForList(anyString(), (Object[]) any());
        when(client.update("phone", 9L, Map.of("status", "sampled", "badge", "重点")))
            .thenReturn(Map.of("id", 9));
        assertThat(service.update("phone", 9L, update)).containsEntry("id", 9);
        verify(client).update("phone", 9L, Map.of("status", "sampled", "badge", "重点"));
    }

    @Test
    void marketAssignmentReceivesWritableConfiguration() {
        CurrentUserContext.set(new CurrentUser(8L, "market", "市场负责人", false));
        doReturn(user("market", "市场负责人", false)).when(jdbc).queryForList(anyString(), (Object[]) any());
        when(jdbc.queryForObject(anyString(), any(Class.class), any())).thenReturn(1L);

        assertThat(service.config()).containsEntry("enabled", true).containsEntry("writable", true);
    }

    @Test
    void repeatedPromotionReturnsTheExistingLinkWithoutCreatingAnotherItem() {
        CurrentUserContext.set(new CurrentUser(1L, "admin", "管理员", true));
        doReturn(Map.of("id", 9, "kind", "phone", "model", "Pixel 12"))
            .when(client).detail("phone", 9L);
        doReturn(user("admin", "管理员", true)).when(jdbc).queryForList(anyString(), (Object[]) any());
        doReturn(java.util.List.of(Map.of(
            "sourceKind", "phone", "sourceId", 9L, "itemId", 41L,
            "promotedById", 1L, "promotedByName", "管理员"
        ))).when(jdbc).queryForList(org.mockito.ArgumentMatchers.contains("plm_market_watch_link"),
            (Object) any(), (Object) any());

        Map<String,Object> result = service.promote(
            new Promote("phone", 9L, "create", null, 3L, "透明壳", "Pixel 12", null, null),
            mock(jakarta.servlet.http.HttpServletRequest.class)
        );

        assertThat(result).containsEntry("itemId", 41L).containsEntry("alreadyPromoted", true);
        verify(collaboration, never()).createItem(any(), any());
        verify(jdbc, never()).update(org.mockito.ArgumentMatchers.contains("insert into plm_market_watch_link"), any(Object[].class));
    }

    @Test
    void createPromotionRejectsAnExistingStyleAndCompatibleModel() {
        CurrentUserContext.set(new CurrentUser(1L, "admin", "管理员", true));
        doReturn(Map.of("id", 9, "kind", "phone", "model", "Pixel 12", "brand", "GOOGLE"))
            .when(client).detail("phone", 9L);
        doReturn(user("admin", "管理员", true)).when(jdbc).queryForList(anyString(), (Object[]) any());
        org.mockito.Mockito.doAnswer(invocation -> {
            String sql = invocation.getArgument(0);
            if (sql.contains("plm_market_watch_link")) return java.util.List.of();
            return java.util.List.of(Map.of("itemId", 41L, "styleName", "透明壳", "compatibleModels", "Pixel 12"));
        }).when(jdbc).queryForList(anyString(), (Object) any(), (Object) any());

        assertThatThrownBy(() -> service.promote(
            new Promote("phone", 9L, "create", null, 3L, "透明壳", "Pixel 12", null, null),
            mock(jakarta.servlet.http.HttpServletRequest.class)
        )).isInstanceOfSatisfying(BusinessException.class,
            error -> assertThat(error.getCode()).isEqualTo(ErrorCodeConstants.CODE_CONFLICT));
        verify(collaboration, never()).createItem(any(), any());
    }

    private static java.util.List<Map<String,Object>> user(String username, String displayName, boolean administrator) {
        return java.util.List.of(Map.of(
            "username", username,
            "display_name", displayName,
            "all_permissions", administrator
        ));
    }

    private static PlatformTransactionManager noOpTransactions() {
        return new PlatformTransactionManager() {
            @Override public TransactionStatus getTransaction(TransactionDefinition definition) { return new SimpleTransactionStatus(); }
            @Override public void commit(TransactionStatus status) {}
            @Override public void rollback(TransactionStatus status) {}
        };
    }
}
