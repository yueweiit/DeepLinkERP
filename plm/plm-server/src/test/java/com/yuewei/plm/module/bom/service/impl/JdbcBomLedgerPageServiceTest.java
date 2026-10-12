package com.yuewei.plm.module.bom.service.impl;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.*;

import com.yuewei.plm.module.bom.dto.BomLedgerQueryDTO;
import com.yuewei.plm.module.bom.service.BomLedgerService;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

class JdbcBomLedgerPageServiceTest {
    @Test
    void productScreenQueriesOnlySummariesAndKeepsZeroBomProducts() {
        CapturingJdbc jdbc = new CapturingJdbc();
        BomLedgerService ledger = mock(BomLedgerService.class);
        BomLedgerQueryDTO query = new BomLedgerQueryDTO(); query.setKeyword("BOM_%"); query.setPage(2);
        var result = new JdbcBomLedgerPageService(jdbc, ledger).products(query);
        assertThat(result.getTotalElements()).isEqualTo(11);
        assertThat(jdbc.sql).contains("left join formal", "count(f.product_bom_id)", "coalesce(max(f.updated_at), p.updated_at)",
            "bf.bom_code ilike ?", "child.model ilike ?", "limit ? offset ?", "o.path");
        assertThat(jdbc.sql).doesNotContain("plm_product_bom_item", "plm_product_bom_cost_snapshot", "plm_product_bom_route_color");
        assertThat(jdbc.args).containsExactly("%BOM\\_\\%%", "%BOM\\_\\%%", "%BOM\\_\\%%", "%BOM\\_\\%%", 50L, 50L);
        verifyNoInteractions(ledger);
    }

    @Test
    void selectedProductUsesServerPagingAndTheSameFormalVisibilityRules() {
        CapturingJdbc jdbc = new CapturingJdbc();
        BomLedgerService ledger = mock(BomLedgerService.class);
        when(ledger.describeFormal(anyList())).thenReturn(List.of());
        new JdbcBomLedgerPageService(jdbc, ledger).boms(7L, new BomLedgerQueryDTO());
        assertThat(jdbc.sql).contains("b.bom_scope = 'formal'", "b.status = 'released'", "b.source_type = 'import'",
            "b.released_by = 'history-import'", "s.status = 'active'", "s.deleted_flag = 0", "o.root_id = ?",
            "order by b.updated_at desc, b.product_bom_id desc limit ? offset ?");
        assertThat(jdbc.args).containsExactly(7L, 50L, 0L);
        verify(ledger, times(1)).describeFormal(anyList());
    }

    private static class CapturingJdbc extends JdbcTemplate {
        String sql; Object[] args;
        @Override public <T> T queryForObject(String sql, Class<T> type, Object... args) {
            if (type == Integer.class) return type.cast(1);
            return type.cast(11L);
        }
        @Override public <T> List<T> query(String sql, RowMapper<T> mapper, Object... args) {
            this.sql = sql; this.args = args; return List.of();
        }
    }
}
