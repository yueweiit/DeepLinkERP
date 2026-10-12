package com.yuewei.plm.module.bom.service.impl;

import com.yuewei.plm.module.bom.service.BomProcessRouteLookup;
import java.util.Optional;
import lombok.RequiredArgsConstructor;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class JdbcBomProcessRouteLookup implements BomProcessRouteLookup {
    private final JdbcTemplate jdbcTemplate;

    @Override
    public Optional<Route> findByCode(Long productId, String routeCode) {
        try {
            return Optional.ofNullable(jdbcTemplate.queryForObject(
                "select process_id, process_code, process_name from plm_process "
                    + "where product_id = ? and process_code = ? and process_type = 'routing' "
                    + "and deleted_flag = 0",
                (result, rowNum) -> new Route(
                    result.getLong("process_id"), result.getString("process_code"), result.getString("process_name")
                ),
                productId,
                routeCode
            ));
        } catch (EmptyResultDataAccessException exception) {
            return Optional.empty();
        }
    }
}
