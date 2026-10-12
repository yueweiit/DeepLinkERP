package com.yuewei.plm.module.code.service;

import static org.assertj.core.api.Assertions.assertThat;
import com.yuewei.plm.module.code.dto.PhoneModelReviewQueryDTO;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

class PhoneModelReviewServiceTest {
    @Test
    void reviewUsesNormalizedNamesAndDoesNotMutateSourceRecords() {
        CapturingJdbc jdbc = new CapturingJdbc();
        PhoneModelReviewService service = new PhoneModelReviewService(jdbc);
        PhoneModelReviewQueryDTO query = new PhoneModelReviewQueryDTO();
        service.page(query);
        assertThat(jdbc.sql).contains("lower(btrim(model))", "group by code_value having count(distinct normalized_name) > 1",
            "order by key limit ? offset ?").doesNotContain("update ", "insert ", "delete ");
        query.setKind("name_many_codes"); query.setPage(2); query.setKeyword("iPhone");
        service.page(query);
        assertThat(jdbc.sql).contains("group by normalized_name having count(distinct code_value) > 1", "key ilike ?");
        assertThat(jdbc.args).containsExactly("%iPhone%", "%iPhone%", "%iPhone%", 50L, 50L);
    }
    private static class CapturingJdbc extends JdbcTemplate {
        String sql; Object[] args;
        @Override public <T> T queryForObject(String sql, Class<T> type, Object... args) { return type.cast(55L); }
        @Override public <T> List<T> query(String sql, RowMapper<T> mapper, Object... args) {
            this.sql = sql; this.args = args; return List.of();
        }
    }
}
