package com.yuewei.plm.module.bom.service.impl;

import com.yuewei.plm.module.bom.service.BomMaterialLookup;
import java.util.Optional;
import lombok.RequiredArgsConstructor;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class JdbcBomMaterialLookup implements BomMaterialLookup {
    private final JdbcTemplate jdbcTemplate;

    @Override
    public Optional<Material> findByCode(String inventoryCode) {
        try {
            Material material = jdbcTemplate.queryForObject(
                "select inventory_id, inventory_code, inventory_name, specification, "
                    + "coalesce(stock_uom, purchase_uom, sales_uom) as unit, supplier_name, unit_cost, currency_code "
                    + "from plm_inventory where inventory_code = ? and deleted_flag = 0",
                (result, rowNum) -> new Material(
                    result.getLong("inventory_id"),
                    result.getString("inventory_code"),
                    result.getString("inventory_name"),
                    result.getString("specification"),
                    result.getString("unit"),
                    result.getString("supplier_name"),
                    result.getBigDecimal("unit_cost"),
                    result.getString("currency_code")
                ),
                inventoryCode
            );
            return Optional.ofNullable(material);
        } catch (EmptyResultDataAccessException exception) {
            return Optional.empty();
        }
    }
}
