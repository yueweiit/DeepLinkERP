package com.yuewei.plm.module.pilot;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.common.security.CurrentUserContext;
import com.yuewei.plm.module.operationlog.entity.OperationLog;
import com.yuewei.plm.module.operationlog.repository.OperationLogRepository;
import com.yuewei.plm.module.operationlog.service.OperationLogCreateCommand;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.operationlog.service.impl.OperationLogServiceImpl;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.aop.framework.ProxyFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.transaction.IllegalTransactionStateException;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.annotation.AnnotationTransactionAttributeSource;
import org.springframework.transaction.interceptor.TransactionInterceptor;
import org.springframework.transaction.support.AbstractPlatformTransactionManager;
import org.springframework.transaction.support.DefaultTransactionStatus;
import org.springframework.transaction.support.SmartTransactionObject;

/** Real Spring transaction boundaries with mocked persistence, no local/production database. */
class PilotUserServiceTest {
    @AfterEach void clearContext() { CurrentUserContext.clear(); }

    @Test
    void accountGrantAuditUsesRealActorAndRollsBackIfRequiredLogFails() throws Exception {
        var jdbc = mock(JdbcTemplate.class);
        when(jdbc.queryForList(anyString(), any(Object[].class))).thenAnswer(call -> {
            String sql = call.getArgument(0);
            if (sql.contains("u.display_name")) return List.of(Map.of(
                "displayName", "原名称", "departmentName", "工程", "status", "active", "allPermissions", false,
                "role", "domestic", "permissionsJson", "[]", "allObjects", false,
                "dingtalkUserId", "before-ding", "version", 1L));
            if (sql.contains("u.username,u.all_permissions")) return List.of(Map.of(
                "username", "newman", "all_permissions", false, "version_no", 1L));
            return List.of();
        });
        when(jdbc.queryForList(anyString(), eq(String.class), any(Object[].class))).thenReturn(List.of("engineering"));
        when(jdbc.queryForObject(anyString(), eq(Long.class), any(Object[].class))).thenReturn(0L);
        var access = mock(PilotAccessService.class);
        var serverActor = new CurrentUser(9L, "real-admin", "真实管理员", true);
        when(access.actor()).thenReturn(serverActor);
        var encoder = mock(PasswordEncoder.class);
        when(encoder.encode(anyString())).thenReturn("encoded-password-for-test");
        var repository = mock(OperationLogRepository.class);
        List<OperationLog> written = new ArrayList<>();
        when(repository.insert(any(OperationLog.class))).thenAnswer(call -> {
            OperationLog log = call.getArgument(0); log.setLogId(21L); written.add(log); return 1;
        });
        var transactions = new RecordingTransactions();
        OperationLogService logs = proxy(new OperationLogServiceImpl(repository), transactions, OperationLogService.class);
        PilotUserService users = proxy(new PilotUserService(jdbc, new ObjectMapper(), access, encoder, logs), transactions, PilotUserService.class);
        CurrentUserContext.set(new CurrentUser(123L, "forged-admin", "不可信显示名", false));
        var input = new PilotUserService.UserInput("newman", " New Man ", " 试点 ", "domestic", "active", true,
            " after-ding ", null, List.of("engineering"), List.of(), "changed-password-for-test", 1L);

        assertThatThrownBy(() -> logs.logRequired(OperationLogCreateCommand.builder().build(), serverActor))
            .isInstanceOf(IllegalTransactionStateException.class);
        assertThat(users.save(5L, input, null)).containsEntry("userId", 5L);
        assertThat(transactions.commits).isEqualTo(1); assertThat(transactions.rollbacks).isZero();
        assertThat(written).hasSize(1);
        OperationLog audit = written.get(0);
        assertThat(audit.getOperatorUserId()).isEqualTo(9L);
        assertThat(audit.getOperatorUserName()).isEqualTo("真实管理员");
        assertThat(audit.getAction()).isEqualTo("PILOT_USER_GRANTS_SAVE");
        var detail = new ObjectMapper().readTree(audit.getDetailJson());
        assertThat(detail.at("/before/allObjects").booleanValue()).isFalse();
        assertThat(detail.at("/after/allObjects").booleanValue()).isTrue();
        assertThat(detail.at("/before/dingtalkUserId").textValue()).isEqualTo("before-ding");
        assertThat(detail.at("/after/dingtalkUserId").textValue()).isEqualTo("after-ding");
        assertThat(detail.at("/after/displayName").textValue()).isEqualTo("New Man");
        assertThat(detail.path("passwordChanged").booleanValue()).isTrue();
        assertThat(audit.getDetailJson()).doesNotContain("changed-password-for-test", "encoded-password-for-test", "forged-admin");

        when(repository.insert(any(OperationLog.class))).thenThrow(new IllegalStateException("audit unavailable"));
        assertThatThrownBy(() -> users.save(5L, input, null)).isInstanceOf(IllegalStateException.class).hasMessage("audit unavailable");
        assertThat(transactions.commits).isEqualTo(1); assertThat(transactions.rollbacks).isEqualTo(1);
    }

    @SuppressWarnings("deprecation")
    private <T> T proxy(Object target, RecordingTransactions transactions, Class<T> type) {
        var proxy = new ProxyFactory(target);
        proxy.setProxyTargetClass(!type.isInterface());
        proxy.addAdvice(new TransactionInterceptor(transactions, new AnnotationTransactionAttributeSource()));
        return type.cast(proxy.getProxy());
    }

    private static final class RecordingTransactions extends AbstractPlatformTransactionManager {
        private final State state = new State(); int commits; int rollbacks;
        @Override protected Object doGetTransaction() { return state; }
        @Override protected boolean isExistingTransaction(Object transaction) { return ((State) transaction).active; }
        @Override protected void doBegin(Object transaction, TransactionDefinition definition) { state.active = true; state.rollbackOnly = false; }
        @Override protected void doCommit(DefaultTransactionStatus status) { commits++; }
        @Override protected void doRollback(DefaultTransactionStatus status) { rollbacks++; }
        @Override protected void doSetRollbackOnly(DefaultTransactionStatus status) { state.rollbackOnly = true; }
        @Override protected void doCleanupAfterCompletion(Object transaction) { state.active = false; }
        private static final class State implements SmartTransactionObject {
            boolean active; boolean rollbackOnly;
            @Override public boolean isRollbackOnly() { return rollbackOnly; }
            @Override public void flush() {}
        }
    }
}
