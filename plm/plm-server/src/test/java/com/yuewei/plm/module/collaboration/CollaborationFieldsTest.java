package com.yuewei.plm.module.collaboration;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.exception.BusinessException;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.Map;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;
import static com.yuewei.plm.module.collaboration.CollaborationFields.*;

class CollaborationFieldsTest {
    private final ObjectMapper json=new ObjectMapper();
    private Object value(String entity,String field,Object value) {return normalise(field(entity,field),json.valueToTree(value));}

    @Test void unknownAndZeroAreDifferentAndCountsNeverInferStockOrEquality() {
        assertThat(value("item","pcTotal",null)).isNull();
        assertThat(value("item","tpuTotal","0")).isEqualTo(0L);
        assertThat(value("item","finishedTotal","5400")).isEqualTo(5400L);
        for(String bad:new String[]{"-1","1.5","9007199254740992","OK 5400"})
            assertThatThrownBy(()->value("item","pcTotal",bad)).isInstanceOf(BusinessException.class);
    }
    @Test void codeRetainsLeadingZerosAndCurrencyIsExplicit() {
        assertThat(value("item","phoneModelCode","0001")).isEqualTo("0001");
        assertThatThrownBy(()->value("item","phoneModelCode",1)).isInstanceOf(BusinessException.class);
        assertThat(value("item","priceCurrency","mxn")).isEqualTo("MXN");
        assertThat(value("item","priceCurrency","UNKNOWN")).isEqualTo("UNKNOWN");
        assertThatThrownBy(()->value("item","priceCurrency","$")).isInstanceOf(BusinessException.class);
        assertThat(value("item","phonePrice","0.00")).isEqualTo(new BigDecimal("0.00"));
    }
    @Test void datesAreStrictAndTimeAnomaliesAreWarningsNotAutomaticCorrections() {
        assertThat(parseDate("21/08/2026")).isEqualTo(LocalDate.of(2026,8,21));
        assertThat(parseDate("2026年8月21日")).isEqualTo(LocalDate.of(2026,8,21));
        assertThat(parseDate("暂无数据")).isNull();
        assertThatThrownBy(()->parseDate("2026-02-30")).isInstanceOf(BusinessException.class);
        assertThatThrownBy(()->parseDate("8月21日")).isInstanceOf(BusinessException.class);
        assertThat(dateWarnings(Map.of("openedDate","2026-08-21","actualShipDate","2026-08-10","actualMexicoArrivalDate","2026-08-01")))
            .containsExactly("实际发模早于开模日期","抵达墨西哥早于实际发模");
    }
    @Test void fieldAllowlistAndSafeLinksRejectInjectedColumnsAndActors() {
        assertThatThrownBy(()->field("item","actorId")).isInstanceOf(BusinessException.class);
        assertThatThrownBy(()->field("mold_set","pcTotal")).isInstanceOf(BusinessException.class);
        assertThat(value("item","referenceUrl","https://example.com/phone\nhttp://example.org/spec")).isNotNull();
        assertThatThrownBy(()->value("item","referenceUrl","javascript:alert(1)")).isInstanceOf(BusinessException.class);
    }
    @Test void searchTodoRespectsAssignedGroupsAndNeverClaimsCountryArrivalIsFactoryCompletion() {
        assertThat(CollaborationRepository.missingSql("production",java.util.Set.of("engineering"))).isEqualTo("false");
        assertThat(CollaborationRepository.missingSql("delivery",java.util.Set.of("mexico"))).contains("actual_ship_date is not null", "factory_arrival_date is null");
        assertThat(CollaborationRepository.statusSql("delivery")).contains("mexico_arrived").doesNotContain("factory_delivered");
        assertThat(CollaborationImportService.brandConflict("Xiaomi","OPPO A5")).isTrue();
        assertThat(CollaborationImportService.brandConflict("HONOR","Honor X8B")).isFalse();
    }
    @Test void customerBilingualHeadersAreMappedWithoutGuessingBusinessValues() {
        assertThat(CollaborationImportService.header("款式\r\nEstilo")).isEqualTo("styleName");
        assertThat(CollaborationImportService.header("型号\r\nModelo")).isEqualTo("compatibleModels");
        assertThat(CollaborationImportService.header("开模日期 Fecha de fabricación del molde")).isEqualTo("openedDate");
        assertThat(CollaborationImportService.header("计划到达工厂日期\r\nFecha prevista de llegada a fábrica")).isEqualTo("plannedFactoryArrivalDate");
    }
    @Test void explicitBrandNamesAreRecognisedButCodesAndAmbiguousAliasesAreNotGuessed() {
        assertThat(brandFromModel("Apple iPhone 18 Pro Max")).isEqualTo("Apple");
        assertThat(brandFromModel("Samsung Galaxy A37 5G")).isEqualTo("Samsung");
        assertThat(brandFromModel("  HONOR X8B  ")).isEqualTo("HONOR");
        assertThat(brandFromModel("SM A04/A04S")).isNull();assertThat(brandFromModel("Appleton A5")).isNull();
        assertThat(brandFromModel("IP18PRO/18PROMAX")).isNull();
    }
}
