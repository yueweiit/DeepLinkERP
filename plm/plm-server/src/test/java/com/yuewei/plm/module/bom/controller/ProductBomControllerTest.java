package com.yuewei.plm.module.bom.controller;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;

class ProductBomControllerTest {

    @Test
    void controllersExposeWorkbenchImportLedgerAndSkuActions() throws Exception {
        String workbench = Files.readString(Path.of(
            "src/main/java/com/yuewei/plm/module/bom/controller/ProductBomController.java"
        ));
        String ledger = Files.readString(Path.of(
            "src/main/java/com/yuewei/plm/module/bom/controller/BomLedgerController.java"
        ));

        assertThat(workbench).contains("/boms/{bomId}/routes");
        assertThat(workbench).contains("/products/{productId}/test-bom");
        assertThat(workbench).contains("/products/{productId}/test-bom/confirm");
        assertThat(workbench).contains("/boms/{bomId}/costs/recalculate");
        assertThat(workbench).contains("/boms/{bomId}/submit-review");
        assertThat(workbench).contains("/boms/{bomId}/publish");
        assertThat(workbench).contains("/boms/{bomId}/copy-version");
        assertThat(workbench).contains("/products/{productId}/boms/inherit");
        assertThat(workbench).contains("/products/{productId}/boms/import/preview");
        assertThat(workbench).contains("/boms/import/{importToken}/commit");
        assertThat(workbench).contains("/boms/import/template");
        assertThat(Files.readString(Path.of(
            "src/main/java/com/yuewei/plm/module/bom/controller/BomMaterialLookupController.java"
        ))).contains("/inventories/material-lookup");
        assertThat(ledger).contains("/bom-ledger");
        assertThat(ledger).contains("/boms/{bomId}/skus");
        assertThat(ledger).contains("/process-routes/{routeId}/skus");
        assertThat(ledger).contains("/products/{productId}/bom-summary");
    }
}
