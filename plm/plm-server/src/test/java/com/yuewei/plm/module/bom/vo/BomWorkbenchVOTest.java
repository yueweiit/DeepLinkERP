package com.yuewei.plm.module.bom.vo;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import org.junit.jupiter.api.Test;

class BomWorkbenchVOTest {

    @Test
    void workbenchModelsExposeStableRouteColorCostAndLedgerFields() throws Exception {
        List<String> sources = List.of(
            "src/main/java/com/yuewei/plm/module/bom/entity/ProductBomRoute.java",
            "src/main/java/com/yuewei/plm/module/bom/entity/ProductBomRouteColor.java",
            "src/main/java/com/yuewei/plm/module/bom/entity/ProductBomCostSnapshot.java",
            "src/main/java/com/yuewei/plm/module/bom/entity/ProductBomImportBatch.java",
            "src/main/java/com/yuewei/plm/module/bom/vo/ProductBomWorkbenchVO.java",
            "src/main/java/com/yuewei/plm/module/bom/vo/BomLedgerRowVO.java",
            "src/main/java/com/yuewei/plm/module/bom/vo/BomSkuRowVO.java"
        );
        assertThat(sources).allSatisfy(source -> assertThat(Files.exists(Path.of(source))).isTrue());

        assertThat(ProductBomRouteVO.class)
            .hasDeclaredFields(
                "productBomRouteId", "productBomId", "processId", "routeCode", "routeName",
                "status", "colors", "items", "costSnapshot"
            );
        assertThat(ProductBomCostSnapshotVO.class)
            .hasDeclaredFields(
                "materialCost", "lossCost", "processCost", "packageCost", "laborCost",
                "toolingCost", "otherCost", "totalCost", "currencyCode", "calculatedAt"
            );
    }
}
