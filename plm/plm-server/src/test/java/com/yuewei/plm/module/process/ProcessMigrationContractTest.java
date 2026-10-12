package com.yuewei.plm.module.process;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;

class ProcessMigrationContractTest {

    @Test
    void processCodeUniqueIndexIgnoresSoftDeletedRows() throws Exception {
        Path migrationPath = Path.of("src/main/resources/db/migration/V20260718_1002__process_code_active_unique_index.sql");

        assertThat(Files.exists(migrationPath)).isTrue();

        String migration = Files.readString(migrationPath).toLowerCase();
        assertThat(migration).contains("alter table if exists plm_process");
        assertThat(migration).contains("drop constraint if exists uk_plm_process_code");
        assertThat(migration).contains("drop index if exists uk_plm_process_code");
        assertThat(migration).contains("create unique index if not exists uk_plm_process_code");
        assertThat(migration).contains("on plm_process (process_code)");
        assertThat(migration).contains("where process_code is not null and deleted_flag = 0");
    }
}
