package com.yuewei.plm.module.pilotdelivery;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.module.bom.entity.ProductBom;
import com.yuewei.plm.module.pilot.PilotAccessService;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class BomReleaseDeliveryServiceTest {
    final ObjectMapper json=new ObjectMapper().findAndRegisterModules();
    ProductBom bom(){var b=new ProductBom();b.setProductBomId(7L);b.setProductId(8L);b.setBomCode("BOM-7");b.setVersionNo("v1");b.setCurrencyCode("CNY");b.setBomScope("formal");b.setBomType("formal");b.setStatus("released");return b;}
    static class Source extends JdbcTemplate {
        String snapshot,fingerprint;List<Map<String,Object>> items=List.of(Map.of("item_code","MAT-1","quantity",2));
        @Override public List<Map<String,Object>> queryForList(String sql,Object...args){return sql.contains("plm_product_bom_item")?items:List.of();}
        @Override public int update(String sql,Object...args){if(sql.startsWith("insert into plm_pilot_bom_release")&&fingerprint==null){snapshot=args[3].toString();fingerprint=args[4].toString();}return 1;}
        @Override public <T>T queryForObject(String sql,Class<T> type,Object...args){return type.cast(fingerprint);}
    }
    @Test void draftTestAndUnknownScopesNeverCreateSnapshotsOrDeliveries() {
        var source=new Source();var queue=mock(PilotDeliveryQueue.class);var access=mock(PilotAccessService.class);var service=new BomReleaseDeliveryService(source,json,queue,access);var b=bom();b.setStatus("draft");assertThatThrownBy(()->service.released(b)).isInstanceOf(BusinessException.class);b.setStatus("released");b.setBomScope("test");assertThatThrownBy(()->service.released(b)).isInstanceOf(BusinessException.class);b.setBomScope(null);assertThatThrownBy(()->service.released(b)).isInstanceOf(BusinessException.class);assertThat(source.snapshot).isNull();verifyNoInteractions(queue);
    }
    @Test void publishedSnapshotIsImmutableAndDuplicateEventIsStable()throws Exception {
        var source=new Source();var queue=mock(PilotDeliveryQueue.class);when(queue.encode(any())).thenAnswer(a->json.writeValueAsString(a.getArgument(0)));var access=mock(PilotAccessService.class);when(access.actorId()).thenReturn(19L);var service=new BomReleaseDeliveryService(source,json,queue,access);var b=bom();service.released(b);String original=source.snapshot;service.released(b);verify(queue,times(2)).enqueue(eq("erp_bom"),eq("plm-bom:7:v1"),any(),eq(19L));assertThat(json.readTree(original).path("items").get(0).path("item_code").asText()).isEqualTo("MAT-1");
        source.items=List.of(Map.of("item_code","MAT-2","quantity",2));assertThatThrownBy(()->service.released(b)).hasMessageContaining("已固定");assertThat(source.snapshot).isEqualTo(original);verify(queue,times(2)).enqueue(anyString(),anyString(),any(),anyLong());
    }
    @Test void serverPublicationAndProductPermissionsAreRequiredBeforeReadingMaterials() {
        var source=mock(JdbcTemplate.class);var access=mock(PilotAccessService.class);doThrow(new BusinessException(40103,"没有发布权限")).when(access).requirePermission("bom:publish");var service=new BomReleaseDeliveryService(source,json,mock(PilotDeliveryQueue.class),access);assertThatThrownBy(()->service.released(bom())).hasMessageContaining("权限");verifyNoInteractions(source);
    }
}
