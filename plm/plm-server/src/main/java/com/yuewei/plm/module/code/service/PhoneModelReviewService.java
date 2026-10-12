package com.yuewei.plm.module.code.service;

import com.yuewei.plm.common.vo.PageVO;
import com.yuewei.plm.module.code.dto.PhoneModelReviewQueryDTO;
import com.yuewei.plm.module.code.vo.PhoneModelReviewVO;
import java.sql.Array;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

@Service
@RequiredArgsConstructor
public class PhoneModelReviewService {
    private final JdbcTemplate jdbc;

    @Transactional(readOnly = true)
    public PageVO<PhoneModelReviewVO> page(PhoneModelReviewQueryDTO query) {
        boolean byCode = !"name_many_codes".equals(query.getKind());
        String group = byCode ? "code_value" : "normalized_name";
        String distinct = byCode ? "normalized_name" : "code_value";
        String cte = """
            with source as (
              select btrim(phone_model_code) as code_value, btrim(model) as model_name,
                     lower(btrim(model)) as normalized_name
                from plm_product where deleted_flag = 0
                 and nullif(btrim(phone_model_code), '') is not null and nullif(btrim(model), '') is not null
            ), conflicts as (
              select %s as key, array_agg(distinct code_value order by code_value) as code_values,
                     array_agg(distinct model_name order by model_name) as model_names, count(*) as source_count
                from source group by %s having count(distinct %s) > 1
            )
            """.formatted(group, group, distinct);
        List<Object> args = new ArrayList<>();
        String filter = "";
        if (StringUtils.hasText(query.getKeyword())) {
            filter = " where key ilike ? or array_to_string(code_values, ' ') ilike ? or array_to_string(model_names, ' ') ilike ?";
            String pattern = "%" + query.getKeyword().trim().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%";
            for (int i = 0; i < 3; i++) args.add(pattern);
        }
        Long count = jdbc.queryForObject(cte + "select count(*) from conflicts" + filter, Long.class, args.toArray());
        long total = count == null ? 0 : count;
        args.add(query.getSize()); args.add((query.getPage() - 1) * query.getSize());
        List<PhoneModelReviewVO> rows = jdbc.query(cte + "select * from conflicts" + filter
            + " order by key limit ? offset ?", (rs, row) -> new PhoneModelReviewVO(rs.getString("key"),
                strings(rs.getArray("code_values")), strings(rs.getArray("model_names")), rs.getLong("source_count")), args.toArray());
        return new PageVO<>(rows, query.getPage(), query.getSize(), total, (total + query.getSize() - 1) / query.getSize());
    }

    private static List<String> strings(Array value) throws SQLException {
        if (value == null) return List.of();
        try { return Arrays.asList((String[]) value.getArray()); }
        finally { value.free(); }
    }
}
