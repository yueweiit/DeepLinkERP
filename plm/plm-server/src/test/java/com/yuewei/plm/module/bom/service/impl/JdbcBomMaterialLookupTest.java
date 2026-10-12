package com.yuewei.plm.module.bom.service.impl;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.yuewei.plm.module.bom.service.BomMaterialLookup;
import java.math.BigDecimal;
import java.sql.ResultSet;
import java.sql.SQLException;
import org.junit.jupiter.api.Test;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

class JdbcBomMaterialLookupTest {

    @Test
    void mapsInventorySnapshotFieldsForMaterialCodeLookup() {
        JdbcBomMaterialLookup lookup = new JdbcBomMaterialLookup(new StubJdbcTemplate(true));

        BomMaterialLookup.Material material = lookup.findByCode("MAT-001").orElseThrow();

        assertThat(material.inventoryId()).isEqualTo(9L);
        assertThat(material.inventoryCode()).isEqualTo("MAT-001");
        assertThat(material.inventoryName()).isEqualTo("TPU 原料 85A");
        assertThat(material.specification()).isEqualTo("25kg / 包");
        assertThat(material.unit()).isEqualTo("kg");
        assertThat(material.supplierName()).isEqualTo("东莞塑胶 A");
        assertThat(material.unitCost()).isEqualByComparingTo("25.50");
        assertThat(material.currencyCode()).isEqualTo("CNY");
    }

    @Test
    void returnsEmptyWhenInventoryCodeDoesNotMatch() {
        JdbcBomMaterialLookup lookup = new JdbcBomMaterialLookup(new StubJdbcTemplate(false));

        assertThat(lookup.findByCode("INV-UNKNOWN-001")).isEmpty();
    }

    private static final class StubJdbcTemplate extends JdbcTemplate {
        private final boolean matched;

        private StubJdbcTemplate(boolean matched) {
            this.matched = matched;
        }

        @Override
        public <T> T queryForObject(String sql, RowMapper<T> rowMapper, Object... args) {
            if (!matched) {
                throw new EmptyResultDataAccessException(1);
            }
            try {
                ResultSet result = mock(ResultSet.class);
                when(result.getLong("inventory_id")).thenReturn(9L);
                when(result.getString("inventory_code")).thenReturn("MAT-001");
                when(result.getString("inventory_name")).thenReturn("TPU 原料 85A");
                when(result.getString("specification")).thenReturn("25kg / 包");
                when(result.getString("unit")).thenReturn("kg");
                when(result.getString("supplier_name")).thenReturn("东莞塑胶 A");
                when(result.getBigDecimal("unit_cost")).thenReturn(new BigDecimal("25.50"));
                when(result.getString("currency_code")).thenReturn("CNY");
                return rowMapper.mapRow(result, 0);
            } catch (SQLException exception) {
                throw new IllegalStateException(exception);
            }
        }
    }
}
