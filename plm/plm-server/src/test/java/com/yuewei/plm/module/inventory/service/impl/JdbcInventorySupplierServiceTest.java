package com.yuewei.plm.module.inventory.service.impl;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.yuewei.plm.module.inventory.vo.InventorySupplierCenterSnapshotVO;
import java.math.BigDecimal;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

class JdbcInventorySupplierServiceTest {

    @Test
    void aggregatesInventoryRowsAsSupplierCenterSnapshot() {
        JdbcInventorySupplierService service = new JdbcInventorySupplierService(new StubJdbcTemplate());

        InventorySupplierCenterSnapshotVO snapshot = service.snapshot();

        assertThat(snapshot.suppliers()).hasSize(1);
        InventorySupplierCenterSnapshotVO.SupplierDetail supplier = snapshot.suppliers().get(0);
        assertThat(supplier.supplierCode()).isEqualTo("SUP-A");
        assertThat(supplier.supplierName()).isEqualTo("东莞塑胶 A");
        assertThat(supplier.status()).isEqualTo("active");
        assertThat(supplier.supplyCategories()).containsExactly("原材料");
        assertThat(supplier.supplyRecords()).hasSize(1);
        assertThat(supplier.supplyRecords().get(0).itemCode()).isEqualTo("INV-MAT-001");
        assertThat(supplier.supplyRecords().get(0).unitPrice()).isEqualByComparingTo("25.50");
        assertThat(snapshot.risks()).hasSize(1);
        assertThat(snapshot.risks().get(0).level()).isEqualTo("medium");
    }

    private static final class StubJdbcTemplate extends JdbcTemplate {
        @Override
        public <T> T queryForObject(String sql, Class<T> requiredType) {
            return requiredType.cast(1);
        }

        @Override
        public <T> List<T> query(String sql, RowMapper<T> rowMapper) {
            try {
                ResultSet result = mock(ResultSet.class);
                when(result.getLong("inventory_id")).thenReturn(9L);
                when(result.getString("inventory_code")).thenReturn("INV-MAT-001");
                when(result.getString("inventory_name")).thenReturn("TPU 原料 85A");
                when(result.getString("inventory_type")).thenReturn("material");
                when(result.getLong("product_id")).thenReturn(20L);
                when(result.wasNull()).thenReturn(false);
                when(result.getString("product_code")).thenReturn("PRD-CD30");
                when(result.getString("product_name")).thenReturn("超队 3.0");
                when(result.getBigDecimal("unit_cost")).thenReturn(new BigDecimal("25.50"));
                when(result.getString("currency_code")).thenReturn("CNY");
                when(result.getInt("lead_time_days")).thenReturn(35);
                when(result.getString("status")).thenReturn("available");
                when(result.getTimestamp("updated_at")).thenReturn(Timestamp.valueOf(LocalDateTime.of(2026, 7, 22, 10, 0)));
                when(result.getString("supplier_name")).thenReturn("东莞塑胶 A");
                when(result.getString("supplier_code")).thenReturn("SUP-A");
                return List.of(rowMapper.mapRow(result, 0));
            } catch (SQLException exception) {
                throw new IllegalStateException(exception);
            }
        }
    }
}
