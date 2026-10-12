package com.yuewei.plm.module.operationlog.service.impl;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.clearInvocations;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.exception.GlobalExceptionHandler;
import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.common.security.CurrentUserContext;
import com.yuewei.plm.common.vo.PageVO;
import com.yuewei.plm.module.operationlog.constant.OperationActionConstants;
import com.yuewei.plm.module.operationlog.controller.OperationLogController;
import com.yuewei.plm.module.operationlog.dto.OperationLogQueryDTO;
import com.yuewei.plm.module.operationlog.entity.OperationLog;
import com.yuewei.plm.module.operationlog.repository.OperationLogRepository;
import com.yuewei.plm.module.operationlog.service.OperationLogCreateCommand;
import com.yuewei.plm.module.operationlog.service.OperationLogDetails;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.operationlog.vo.OperationLogVO;
import com.yuewei.plm.module.pilot.PilotAccessService;
import jakarta.servlet.http.HttpServletRequest;
import java.time.LocalDateTime;
import java.util.List;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

class OperationLogServiceImplTest {

    @AfterEach
    void tearDown() {
        CurrentUserContext.clear();
    }

    @Test
    void logSuccessFillsOperatorRequestAndBusinessFieldsAndRedactsDetails() {
        OperationLogRepository repository = mock(OperationLogRepository.class);
        OperationLogServiceImpl service = new OperationLogServiceImpl(repository);
        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getHeader("X-Request-Id")).thenReturn("m1-apifox-log-001");
        when(request.getMethod()).thenReturn("POST");
        when(request.getRequestURI()).thenReturn("/api/v1/operation-logs/test");
        when(request.getRemoteAddr()).thenReturn("127.0.0.1");
        when(request.getHeader("User-Agent")).thenReturn("JUnit");
        CurrentUserContext.set(new CurrentUser(1L, "engineer01", "工程部用户一", true));
        ArgumentCaptor<OperationLog> captor = ArgumentCaptor.forClass(OperationLog.class);
        when(repository.insert(any(OperationLog.class))).thenAnswer(call -> {
            call.<OperationLog>getArgument(0).setLogId(11L);
            return 1;
        });

        Long logId = service.logSuccess(OperationLogCreateCommand.builder()
            .action(OperationActionConstants.TEST_WRITE)
            .businessType("M1_TEST")
            .businessId("apifox-001")
            .businessCode("M1-TEST-001")
            .businessName("M1 Apifox 测试日志")
            .detailJson("{\"source\":\"junit\",\"password\":\"plain-secret\",\"passwordChanged\":true,"
                + "\"nested\":[{\"access_token\":\"session-secret\",\"password_hash\":\"hash-secret\"}],"
                + "\"url\":\"https://example.test/?token=query-secret\",\"header\":\"Bearer bearer-secret\","
                + "\"note\":\"password: colon-secret authorization: header-secret secret: app-secret\",\"unitCost\":12}")
            .request(request)
            .build());

        verify(repository).insert(captor.capture());
        OperationLog log = captor.getValue();
        assertThat(logId).isEqualTo(log.getLogId());
        assertThat(log.getRequestId()).isEqualTo("m1-apifox-log-001");
        assertThat(log.getOperatorUserId()).isEqualTo(1L);
        assertThat(log.getOperatorUserName()).isEqualTo("工程部用户一");
        assertThat(log.getAction()).isEqualTo(OperationActionConstants.TEST_WRITE);
        assertThat(log.getBusinessType()).isEqualTo("M1_TEST");
        assertThat(log.getCreatedAt()).isNotNull();
        assertThat(log.getCreatedBy()).isEqualTo("工程部用户一");
        assertThat(log.getDeletedFlag()).isZero();
        assertThat(log.getDetailJson()).contains("\"passwordChanged\":true", "\"unitCost\":12", "[REDACTED]")
            .doesNotContain("plain-secret", "session-secret", "hash-secret", "query-secret", "bearer-secret", "colon-secret", "header-secret", "app-secret");
        log.setDetailJson("{\"authorization\":\"old-secret\",\"passwordChanged\":false,\"before\":{\"clientSecret\":\"old-app-secret\"}}");
        assertThat(OperationLogVO.from(log).getDetailJson()).contains("\"passwordChanged\":false")
            .doesNotContain("old-secret", "old-app-secret");
        assertThat(OperationLogDetails.sanitize("password=unstructured-secret"))
            .contains("非结构化日志详情已隐藏").doesNotContain("unstructured-secret");
        assertThat(OperationLogDetails.sanitize("{\"passwordChanged\":\"not-a-boolean-secret\"}"))
            .doesNotContain("not-a-boolean-secret");
    }

    @Test
    void legacyFailureStaysBestEffortButRequiredAuditPropagatesIt() throws Exception {
        OperationLogRepository repository = mock(OperationLogRepository.class);
        doThrow(new IllegalStateException("operation log table missing")).when(repository).insert(any(OperationLog.class));
        OperationLogServiceImpl service = new OperationLogServiceImpl(repository);

        Long logId = service.logSuccess(OperationLogCreateCommand.builder()
            .action(OperationActionConstants.TEST_WRITE)
            .businessType("M1_TEST")
            .businessId("apifox-001")
            .businessCode("M1-TEST-001")
            .businessName("M1 Apifox 测试日志")
            .detailJson("{\"source\":\"junit\"}")
            .build());

        assertThat(logId).isNull();
        var command = OperationLogCreateCommand.builder().action("PILOT_USER_GRANTS_SAVE").build();
        var actor = new CurrentUser(9L, "admin", "管理员", true);
        assertThatThrownBy(() -> service.logRequired(command, actor))
            .isInstanceOf(IllegalStateException.class).hasMessage("operation log table missing");
        assertThatThrownBy(() -> service.logRequired(command, null)).isInstanceOf(BusinessException.class);
        assertThat(OperationLogServiceImpl.class.getMethod("logRequired", OperationLogCreateCommand.class, CurrentUser.class)
            .getAnnotation(Transactional.class).propagation()).isEqualTo(Propagation.MANDATORY);
        assertThat(OperationLogServiceImpl.class.getMethod("logSuccess", OperationLogCreateCommand.class)
            .getAnnotation(Transactional.class).propagation()).isEqualTo(Propagation.NOT_SUPPORTED);
    }

    @Test
    @SuppressWarnings({"rawtypes", "unchecked"})
    void inclusiveTimeFiltersHaveStablePaginationAndRejectReversedRange() {
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(new MybatisConfiguration(), "operation-log-test"), OperationLog.class);
        var repository = mock(OperationLogRepository.class);
        var service = new OperationLogServiceImpl(repository);
        var query = new OperationLogQueryDTO();
        query.setPage(2); query.setSize(50); query.setAction("PILOT_USER_GRANTS_SAVE");
        query.setCreatedFrom(LocalDateTime.parse("2026-10-12T08:00:00"));
        query.setCreatedTo(LocalDateTime.parse("2026-10-12T10:00:00"));
        var result = new Page<OperationLog>(2, 50, 73);
        var row = new OperationLog(); row.setLogId(12L); row.setDetailJson("{\"token\":\"legacy-token\"}");
        result.setRecords(List.of(row));
        when(repository.selectPage(any(Page.class), any(Wrapper.class))).thenReturn(result);
        var page = service.page(query);
        ArgumentCaptor<LambdaQueryWrapper> filter = ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        verify(repository).selectPage(any(Page.class), filter.capture());
        assertThat(filter.getValue().getSqlSegment()).contains("created_at >=", "created_at <=", "ORDER BY created_at DESC,log_id DESC");
        assertThat(filter.getValue().getParamNameValuePairs().values())
            .contains(query.getCreatedFrom(), query.getCreatedTo(), "PILOT_USER_GRANTS_SAVE");
        assertThat(page.getPage()).isEqualTo(2); assertThat(page.getTotalElements()).isEqualTo(73);
        assertThat(page.getContent().get(0).getDetailJson()).doesNotContain("legacy-token");
        query.setCreatedFrom(query.getCreatedTo().plusSeconds(1));
        clearInvocations(repository);
        assertThat(query.isDateRangeValid()).isFalse();
        assertThatThrownBy(() -> service.page(query)).isInstanceOf(BusinessException.class).hasMessageContaining("开始时间");
        verifyNoInteractions(repository);
        query.setCreatedFrom(query.getCreatedTo());
        assertThat(query.isDateRangeValid()).isTrue();
    }

    @Test
    void originalEndpointsAreAdministratorOnlyAndBindIsoDates() throws Exception {
        var service = mock(OperationLogService.class);
        var access = mock(PilotAccessService.class);
        var mvc = MockMvcBuilders.standaloneSetup(new OperationLogController(service, new ObjectMapper(), access))
            .setControllerAdvice(new GlobalExceptionHandler()).build();
        doThrow(new BusinessException(40103, "仅管理员可以查看日志")).when(access).requireAdministrator();
        mvc.perform(get("/api/v1/operation-logs")).andExpect(status().isForbidden());
        mvc.perform(post("/api/v1/operation-logs/test").contentType(MediaType.APPLICATION_JSON)
            .content("{\"businessType\":\"test\",\"detail\":{\"password\":\"must-not-write\"}}"))
            .andExpect(status().isForbidden());
        verifyNoInteractions(service);
        org.mockito.Mockito.doNothing().when(access).requireAdministrator();
        when(service.page(any())).thenReturn(PageVO.<OperationLogVO>builder().content(List.of()).page(1).size(20).build());
        mvc.perform(get("/api/v1/operation-logs").param("createdFrom", "2026-10-12T08:00:00")
            .param("createdTo", "2026-10-12T10:00:00")).andExpect(status().isOk());
        ArgumentCaptor<OperationLogQueryDTO> query = ArgumentCaptor.forClass(OperationLogQueryDTO.class);
        verify(service).page(query.capture());
        assertThat(query.getValue().getCreatedFrom()).isEqualTo(LocalDateTime.parse("2026-10-12T08:00:00"));
        assertThat(query.getValue().getCreatedTo()).isEqualTo(LocalDateTime.parse("2026-10-12T10:00:00"));
        clearInvocations(service);
        mvc.perform(get("/api/v1/operation-logs").param("createdFrom", "2026-10-13T08:00:00")
            .param("createdTo", "2026-10-12T10:00:00")).andExpect(status().isBadRequest());
        mvc.perform(get("/api/v1/operation-logs").param("createdFrom", "not-a-date")).andExpect(status().isBadRequest());
        verifyNoInteractions(service);
    }
}
