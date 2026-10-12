package com.yuewei.plm.module.bom;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;

class BomWorkbenchMigrationContractTest {

    @Test
    void migrationDefinesRouteColorCostAndImportExtensions() throws Exception {
        Path migrationPath = Path.of(
            "src/main/resources/db/migration/V20260718_1100__bom_workbench_route_cost_import.sql"
        );

        assertThat(Files.exists(migrationPath)).isTrue();

        String migration = Files.readString(migrationPath).toLowerCase();
        assertThat(migration).contains("alter table if exists plm_product_bom");
        assertThat(migration).contains("bom_scope");
        assertThat(migration).contains("test_total_cost");
        assertThat(migration).contains("create table if not exists plm_product_bom_route");
        assertThat(migration).contains("create table if not exists plm_product_bom_route_color");
        assertThat(migration).contains("create table if not exists plm_product_bom_cost_snapshot");
        assertThat(migration).contains("create table if not exists plm_product_bom_import_batch");
        assertThat(migration).contains("product_bom_id");
        assertThat(migration).contains("process_id");
        assertThat(migration).contains("color_name");
        assertThat(migration).contains("currency_code");
        assertThat(migration).contains("import_token");
        assertThat(migration).contains("where status = 'active' and deleted_flag = 0");
        assertThat(migration).contains("created_at");
        assertThat(migration).contains("created_by");
        assertThat(migration).contains("updated_at");
        assertThat(migration).contains("updated_by");
        assertThat(migration).contains("deleted_flag");
    }

    @Test
    void migrationDefinesRouteFormalSelectionForCandidateBomConfirmation() throws Exception {
        Path migrationPath = Path.of(
            "src/main/resources/db/migration/V20260720_1001__bom_route_formal_selection.sql"
        );

        assertThat(Files.exists(migrationPath)).isTrue();

        String migration = Files.readString(migrationPath).toLowerCase();
        assertThat(migration).contains("create table if not exists plm_product_bom_route_formal_selection");
        assertThat(migration).contains("product_bom_route_formal_selection_id");
        assertThat(migration).contains("product_id bigint not null");
        assertThat(migration).contains("product_bom_id bigint not null");
        assertThat(migration).contains("product_bom_route_id bigint not null");
        assertThat(migration).contains("process_id bigint not null");
        assertThat(migration).contains("bom_version_no");
        assertThat(migration).contains("status varchar(24) not null default 'active'");
        assertThat(migration).contains("invalidated_at");
        assertThat(migration).contains("invalidated_reason");
        assertThat(migration).contains("created_at");
        assertThat(migration).contains("created_by");
        assertThat(migration).contains("updated_at");
        assertThat(migration).contains("updated_by");
        assertThat(migration).contains("deleted_flag");
        assertThat(migration).contains("on plm_product_bom_route_formal_selection(product_id, process_id)");
        assertThat(migration).contains("where status = 'active' and deleted_flag = 0");
    }

    @Test
    void migrationAllowsMultipleFormalBomsForOneProcessRoute() throws Exception {
        Path migrationPath = Path.of(
            "src/main/resources/db/migration/V20260805_1100__allow_multiple_formal_boms_per_process.sql"
        );

        assertThat(Files.exists(migrationPath)).isTrue();
        String migration = Files.readString(migrationPath).toLowerCase();
        assertThat(migration).contains("drop index if exists uk_product_bom_route_formal_active");
        assertThat(migration).contains(
            "on plm_product_bom_route_formal_selection(product_id, process_id, product_bom_route_id)"
        );
        assertThat(migration).contains("where status = 'active' and deleted_flag = 0");
    }

    @Test
    void migrationDefinesBomItemSupplierPriceAndManualMaterialSnapshots() throws Exception {
        Path migrationPath = Path.of(
            "src/main/resources/db/migration/V20260721_1000__bom_item_supplier_price_snapshot.sql"
        );

        assertThat(Files.exists(migrationPath)).isTrue();

        String migration = Files.readString(migrationPath).toLowerCase();
        assertThat(migration).contains("alter table if exists plm_product_bom_item");
        assertThat(migration).contains("supplier_code_snapshot");
        assertThat(migration).contains("supplier_name_snapshot");
        assertThat(migration).contains("line_cost_snapshot");
        assertThat(migration).contains("material_source varchar(16) not null default 'inventory'");
        assertThat(migration).contains("unmatched_flag integer not null default 0");
        assertThat(migration).contains("idx_plm_product_bom_item_material_source");
        assertThat(migration).contains("where deleted_flag = 0");
    }

    @Test
    void migrationPromotesImportedBomAndProcessDataToFormalVersions() throws Exception {
        Path migrationPath = Path.of(
            "src/main/resources/db/migration/V20260805_1000__imported_bom_process_formal_versions.sql"
        );

        assertThat(Files.exists(migrationPath)).isTrue();

        String migration = Files.readString(migrationPath).toLowerCase();
        assertThat(migration).contains("update plm_product_bom");
        assertThat(migration).contains("bom_scope = 'formal'");
        assertThat(migration).contains("source_type = 'seed_reference'");
        assertThat(migration).contains("status = 'released'");
        assertThat(migration).contains("frozen_flag = 1");
        assertThat(migration).contains("plm_product_bom_import_batch");
        assertThat(migration).contains("batch.status = 'committed'");
        assertThat(migration).contains("update plm_process");
        assertThat(migration).contains("status = 'confirmed'");
        assertThat(migration).contains("process.process_code like 'route-%-import-%'");
        assertThat(migration).contains("process_type in ('routing', 'operation')");
    }

    @Test
    void migrationRebuildsBomItemLineUniquenessForActiveRowsOnly() throws Exception {
        Path migrationPath = Path.of(
            "src/main/resources/db/migration/V20260722_1000__bom_item_active_line_unique.sql"
        );

        assertThat(Files.exists(migrationPath)).isTrue();

        String migration = Files.readString(migrationPath).toLowerCase();
        assertThat(migration).contains("drop constraint if exists uk_plm_product_bom_item_line");
        assertThat(migration).contains("drop index if exists uk_plm_product_bom_item_line");
        assertThat(migration).contains("create unique index uk_plm_product_bom_item_line");
        assertThat(migration).contains("on plm_product_bom_item (product_bom_id, line_no)");
        assertThat(migration).contains("where deleted_flag = 0");
    }
}
