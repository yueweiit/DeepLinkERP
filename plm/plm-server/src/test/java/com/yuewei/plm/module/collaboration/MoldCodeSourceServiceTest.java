package com.yuewei.plm.module.collaboration;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.config.AppProperties;
import com.yuewei.plm.common.security.SimpleTokenAuthenticationFilter;
import com.yuewei.plm.module.auth.service.TokenSessionService;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import jakarta.servlet.FilterChain;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class MoldCodeSourceServiceTest {
    @Test void sourcePageUsesConstantBatchQueriesRegardlessOfRowCount() {
        var jdbc=mock(JdbcTemplate.class);var collaboration=mock(CollaborationService.class);
        var service=new MoldCodeSourceService(jdbc,new ObjectMapper(),collaboration);
        when(jdbc.queryForObject(anyString(),eq(Long.class),any(Object[].class))).thenReturn(500L);
        when(jdbc.queryForList(anyString(),any(Object[].class))).thenReturn(java.util.stream.IntStream.range(0,50).mapToObj(i->Map.<String,Object>of("source_code_id",i,"mold_code","MBA200052")).toList());
        var page=service.page(new MoldCodeSourceTypes.Query());
        assertThat(page.getContent()).hasSize(50);assertThat(page.getTotalElements()).isEqualTo(500);
        verify(jdbc,times(1)).queryForObject(anyString(),eq(Long.class),any(Object[].class));
        verify(jdbc,times(1)).queryForList(anyString(),any(Object[].class));verifyNoMoreInteractions(jdbc);
    }
    @Test void newSourceAndReceiveRoutesAreNotPublicAuthenticationBypasses() throws Exception {
        for(String path:List.of("/api/v1/integrations/dingtalk/mold-codes","/api/v1/molds/source-codes","/api/v1/molds/source-codes/erp-previews")) {
            var sessions=mock(TokenSessionService.class);when(sessions.getCurrentUser(null)).thenReturn(Optional.empty());
            var filter=new SimpleTokenAuthenticationFilter(new AppProperties(),sessions,new ObjectMapper().findAndRegisterModules());
            var request=new MockHttpServletRequest("POST",path);var response=new MockHttpServletResponse();var chain=mock(FilterChain.class);
            filter.doFilter(request,response,chain);
            assertThat(response.getStatus()).isEqualTo(401);verifyNoInteractions(chain);
        }
    }
}
