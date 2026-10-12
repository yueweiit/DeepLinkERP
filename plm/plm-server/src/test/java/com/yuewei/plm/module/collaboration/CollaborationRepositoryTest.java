package com.yuewei.plm.module.collaboration;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import static org.assertj.core.api.Assertions.assertThat;

class CollaborationRepositoryTest {
    @Test void pagingUsesTwoQueriesWithBulkLinksAndPartsEvenWithFiftyRecords() {
        CountingJdbc jdbc=new CountingJdbc();
        CollaborationRepository repository=new CollaborationRepository(jdbc,new ObjectMapper());
        CollaborationTypes.Query q=new CollaborationTypes.Query();q.setView("delivery");q.setPage(14);q.setKeyword("A%_");q.setMineOnly(true);
        var page=repository.page(q,Set.of("logistics"));
        assertThat(jdbc.calls).isEqualTo(2);
        assertThat(page.getTotalElements()).isEqualTo(657);assertThat(page.getSize()).isEqualTo(50);
        assertThat(jdbc.sql).contains("jsonb_agg", "plm_collaboration_mold_part pc", "limit ? offset ?", "arrival_confirmed_basis_date is distinct from");
        assertThat(jdbc.sql).contains("order by s.opened_date desc nulls last,s.mold_set_id desc limit ? offset ?")
            .doesNotContain("order by s.updated_at");
        assertThat(jdbc.args).containsExactly("%A\\%\\_%","%A\\%\\_%",50,650L);
    }
    @Test void moldLedgerFiltersAndDetailSummariesRemainTwoBulkQueries() {
        CountingJdbc jdbc=new CountingJdbc();var repository=new CollaborationRepository(jdbc,new ObjectMapper());
        var q=new CollaborationTypes.Query();q.setView("delivery");q.setMoldLedger(true);q.setStatus("partially_arrived");q.setLocation("mexico_factory");q.setPage(2);
        repository.page(q,Set.of("mexico"));
        assertThat(jdbc.calls).isEqualTo(2);assertThat(jdbc.args).containsExactly("partially_arrived","mexico_factory","mexico_factory",50,50L);
        assertThat(jdbc.sql).contains("pc.factory_arrival_date", "tpu.acceptance_status", "source_mold_set_id", "asset_number", "jsonb_agg");
        assertThat(CollaborationRepository.moldStatusSql()).contains("'delivered'").doesNotContain("actual_mexico_arrival_date is not null then 'delivered'");
        for(String view:List.of("market","production")) {
            CountingJdbc ordinary=new CountingJdbc();var query=new CollaborationTypes.Query();query.setView(view);
            new CollaborationRepository(ordinary,new ObjectMapper()).page(query,Set.of());
            assertThat(ordinary.calls).isEqualTo(2);
            assertThat(ordinary.sql).contains("order by i.updated_at desc,i.item_id desc limit ? offset ?")
                .doesNotContain("order by s.opened_date");
        }
    }
    private static class CountingJdbc extends JdbcTemplate {
        int calls;String sql;Object[] args;
        @Override public <T> T queryForObject(String sql,Class<T> type,Object...args) {calls++;return type.cast(657L);}
        @Override public <T> List<T> query(String sql,RowMapper<T> mapper,Object...args) {calls++;this.sql=sql;this.args=args;return List.of();}
    }
}
