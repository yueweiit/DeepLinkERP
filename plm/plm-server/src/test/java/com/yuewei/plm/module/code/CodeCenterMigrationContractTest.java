package com.yuewei.plm.module.code;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;

class CodeCenterMigrationContractTest {
    @Test
    void migrationDefinesCodeItemAndColorReferences() throws Exception {
        String sql = Files.readString(Path.of(
            "src/main/resources/db/migration/V20260719_1002__code_center_color_codes.sql"));

        assertThat(sql).contains("create table if not exists plm_code_item");
        assertThat(sql).contains("code_type, code_value");
        assertThat(sql).contains("add column if not exists code_item_id");
        assertThat(sql).contains("add column if not exists color_code");
    }
}
