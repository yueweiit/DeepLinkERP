package com.yuewei.plm.module.inventory.service.impl;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.yuewei.plm.module.inventory.vo.InventoryCenterSnapshotVO;
import com.yuewei.plm.module.inventory.dto.InventoryCenterQueryDTO;
import java.math.BigDecimal;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

class JdbcInventoryCenterServiceTest {

    @Test
    void paginationAndCombinedFiltersAreAppliedInSql() {
        PagingJdbc jdbc = new PagingJdbc();
        JdbcInventoryCenterService service = new JdbcInventoryCenterService(jdbc,
            Clock.fixed(Instant.parse("2026-10-08T12:00:00Z"), ZoneOffset.UTC));
        InventoryCenterQueryDTO query = new InventoryCenterQueryDTO();
        query.setPage(157); query.setKeyword("A%_"); query.setNodeId("material-group:1"); query.setTimeRange("90d");

        var result = service.page(query);

        assertThat(result.getTotalElements()).isEqualTo(7803);
        assertThat(result.getTotalPages()).isEqualTo(157);
        assertThat(result.getSize()).isEqualTo(50);
        assertThat(jdbc.listSql).contains("ilike ?", "coalesce(parent_group.material_group_id, item_group.material_group_id) = ?",
            "i.updated_at >= ?", "order by i.updated_at desc, i.inventory_id desc limit ? offset ?");
        assertThat(jdbc.listArgs).containsExactly("%A\\%\\_%", "%A\\%\\_%", "%A\\%\\_%", "%A\\%\\_%", "%A\\%\\_%",
            1L, Timestamp.valueOf("2026-07-10 12:00:00"), 50L, 7800L);
        assertThat(jdbc.countSql).contains("i.updated_at >= ?").doesNotContain("limit");
    }

    @Test
    void yearFilterHasAnExclusiveEndAndGroupsDoNotFetchInventoryRows() {
        PagingJdbc jdbc = new PagingJdbc();
        JdbcInventoryCenterService service = new JdbcInventoryCenterService(jdbc,
            Clock.fixed(Instant.parse("2026-10-08T12:00:00Z"), ZoneOffset.UTC));
        InventoryCenterQueryDTO query = new InventoryCenterQueryDTO(); query.setTimeRange("this_year");
        service.page(query);
        assertThat(jdbc.listArgs).containsExactly(Timestamp.valueOf("2026-01-01 00:00:00"),
            Timestamp.valueOf("2027-01-01 00:00:00"), 50L, 0L);
        jdbc.listSql = null;
        assertThat(service.groups().get(0).count()).isEqualTo(7803);
        assertThat(jdbc.listSql).isNull();
    }

    private static class PagingJdbc extends JdbcTemplate {
        String listSql; String countSql; Object[] listArgs;
        @Override public <T> T queryForObject(String sql, Class<T> type) {
            if (type == Integer.class) return type.cast(Integer.valueOf(1));
            return type.cast(Long.valueOf(7803));
        }
        @Override public <T> T queryForObject(String sql, Class<T> type, Object... args) {
            countSql = sql;
            return type.cast(Long.valueOf(7803));
        }
        @Override public <T> List<T> query(String sql, RowMapper<T> mapper, Object... args) {
            listSql = sql; listArgs = args; return List.of();
        }
        @Override public <T> List<T> query(String sql, RowMapper<T> mapper) { return List.of(); }
    }

    @Test
    void snapshotReturnsMaterialGroupTreeAndInventoryRowsFromDatabase() {
        JdbcInventoryCenterService service = new JdbcInventoryCenterService(new StubJdbcTemplate(true));

        InventoryCenterSnapshotVO snapshot = service.snapshot();

        assertThat(snapshot.tree()).hasSize(1);
        assertThat(snapshot.tree().get(0).nodeId()).isEqualTo("all");
        assertThat(snapshot.tree().get(0).children()).hasSize(1);
        InventoryCenterSnapshotVO.InventoryTreeNode major = snapshot.tree().get(0).children().get(0);
        assertThat(major.nodeId()).isEqualTo("material-group:1");
        assertThat(major.label()).isEqualTo("YL 原料");
        assertThat(major.children()).isEmpty();

        assertThat(snapshot.items()).hasSize(1);
        InventoryCenterSnapshotVO.InventoryListRow item = snapshot.items().get(0);
        assertThat(item.itemId()).isEqualTo("9");
        assertThat(item.nodeId()).isEqualTo("material-group:1");
        assertThat(item.code()).isEqualTo("YL000001");
        assertThat(item.inventoryType()).isEqualTo("原材料");
    }

    @Test
    void snapshotFallsBackToAllGroupWhenMaterialGroupTableIsMissing() {
        JdbcInventoryCenterService service = new JdbcInventoryCenterService(new StubJdbcTemplate(false));

        InventoryCenterSnapshotVO snapshot = service.snapshot();

        assertThat(snapshot.tree()).hasSize(1);
        assertThat(snapshot.tree().get(0).nodeId()).isEqualTo("all");
        assertThat(snapshot.tree().get(0).children()).isEmpty();
    }

    private static final class StubJdbcTemplate extends JdbcTemplate {
        private final boolean materialGroupTableExists;

        private StubJdbcTemplate(boolean materialGroupTableExists) {
            this.materialGroupTableExists = materialGroupTableExists;
        }

        @Override
        public <T> T queryForObject(String sql, Class<T> requiredType, Object... args) {
            if (sql.contains("information_schema.tables") && sql.contains("plm_material_group")) {
                return requiredType.cast(materialGroupTableExists ? 1 : 0);
            }
            return requiredType.cast(0);
        }

        @Override
        public <T> T queryForObject(String sql, Class<T> requiredType) {
            if (sql.contains("information_schema.tables") && sql.contains("plm_material_group")) {
                return requiredType.cast(materialGroupTableExists ? 1 : 0);
            }
            return requiredType.cast(0);
        }

        @Override
        public <T> List<T> query(String sql, RowMapper<T> rowMapper) {
            try {
                if (sql.contains("from plm_inventory")) {
                    return List.of(rowMapper.mapRow(inventoryResult(), 0));
                }
                if (sql.contains("from plm_material_group")) {
                    if (!materialGroupTableExists) return List.of();
                    return mapGroups(sql, rowMapper);
                }
                return List.of();
            } catch (SQLException exception) {
                throw new IllegalStateException(exception);
            }
        }

        private static <T> List<T> mapGroups(String sql, RowMapper<T> rowMapper) throws SQLException {
            List<T> rows = new ArrayList<>();
            rows.add(rowMapper.mapRow(groupResult(1L, null, "YL 原料", "category", 103, "YL"), 0));
            if (sql.contains("group_level = 1")) return rows;
            rows.add(rowMapper.mapRow(groupResult(2L, 1L, "000001 原料TPU", "category", 1, "000001"), 1));
            return rows;
        }

        private static ResultSet groupResult(Long id, Long parentId, String label, String nodeType, int count, String groupCode)
            throws SQLException {
            ResultSet result = mock(ResultSet.class);
            when(result.getLong("material_group_id")).thenReturn(id);
            when(result.getLong("parent_material_group_id")).thenReturn(parentId == null ? 0L : parentId);
            when(result.wasNull()).thenReturn(parentId == null);
            when(result.getString("display_name")).thenReturn(label);
            when(result.getString("node_type")).thenReturn(nodeType);
            when(result.getInt("source_record_count")).thenReturn(count);
            when(result.getString("group_code")).thenReturn(groupCode);
            return result;
        }

        private static ResultSet inventoryResult() throws SQLException {
            ResultSet result = mock(ResultSet.class);
            when(result.getLong("inventory_id")).thenReturn(9L);
            when(result.getString("inventory_code")).thenReturn("YL000001");
            when(result.getString("inventory_name")).thenReturn("TPU 85A");
            when(result.getString("specification")).thenReturn("HF-1190AL");
            when(result.getBigDecimal("quantity")).thenReturn(new BigDecimal("0"));
            when(result.getString("stock_uom")).thenReturn("kg");
            when(result.getString("inventory_type")).thenReturn("material");
            when(result.getString("status")).thenReturn("available");
            when(result.getString("supplier_name")).thenReturn("默认供应商");
            when(result.getTimestamp("updated_at")).thenReturn(Timestamp.valueOf(LocalDateTime.of(2026, 7, 27, 9, 30)));
            when(result.getString("product_name")).thenReturn(null);
            when(result.getString("model")).thenReturn(null);
            when(result.getLong("material_group_id")).thenReturn(1L);
            when(result.wasNull()).thenReturn(false);
            return result;
        }
    }
}
