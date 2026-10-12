package com.yuewei.plm.module.bom.entity;

import static org.assertj.core.api.Assertions.assertThat;

import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableName;
import com.yuewei.plm.common.mybatis.typehandler.PostgresJsonbStringTypeHandler;
import org.junit.jupiter.api.Test;

class ProductBomCostSnapshotMappingTest {

    @Test
    void mapsSourceSnapshotJsonAsPostgresJsonb() throws Exception {
        TableName tableName = ProductBomCostSnapshot.class.getAnnotation(TableName.class);
        TableField tableField = ProductBomCostSnapshot.class
            .getDeclaredField("sourceSnapshotJson")
            .getAnnotation(TableField.class);

        assertThat(tableName.value()).isEqualTo("plm_product_bom_cost_snapshot");
        assertThat(tableName.autoResultMap()).isTrue();
        assertThat(tableField.typeHandler()).isEqualTo(PostgresJsonbStringTypeHandler.class);
    }
}
