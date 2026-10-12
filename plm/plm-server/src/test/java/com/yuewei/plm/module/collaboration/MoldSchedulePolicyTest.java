package com.yuewei.plm.module.collaboration;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.exception.BusinessException;
import java.time.LocalDate;
import java.util.*;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

class MoldSchedulePolicyTest {
    private final ObjectMapper json=new ObjectMapper();
    private Map<String,Object> row(String style) {Map<String,Object> r=new LinkedHashMap<>();r.put("styleName",style);r.put("moldSetId",1L);r.put("assetNumber","MS-000001");r.put("compatibleModels","Apple iPhone");r.put("holidayDays",5);r.put("extraDays",0);r.put("openedDate","2026-09-28");r.put("pcAcceptanceStatus","pending");r.put("tpuAcceptanceStatus","pending");r.put("pcStatus","making");r.put("tpuStatus","making");r.put("deliveryStatus","making");return r;}
    @Test void calendarSuggestionsUseExactOriginalStyleCyclesAndDoNotOverwriteConfirmedDates() {
        Map<String,String> expected=Map.of("MB冰盾","2026-10-15","MHA超队","2026-10-16","MBA亮甲2.0","2026-10-17");
        expected.forEach((style,date)->{var r=row(style);r.put("plannedFactoryArrivalDate","2026-10-30");MoldScheduleTypes.enrich(r);assertThat(r).containsEntry("suggestedDeliveryDate",date).containsEntry("plannedFactoryArrivalDate","2026-10-30").containsEntry("suggestedAcceptanceDate","2026-10-31").containsEntry("suggestedProductionDate","2026-11-03");});
        var unknown=row("亮甲别名");MoldScheduleTypes.enrich(unknown);assertThat(unknown.get("suggestedDeliveryDate")).isNull();
    }
    @Test void forecastPlanAndActualStaySeparateAndExtraDaysRemainExplicit() {
        var r=row("MG金刚甲");r.put("extraDays",2);r.put("forecastDeliveryDate","2026-10-21");r.put("actualMexicoArrivalDate","2026-10-05");MoldScheduleTypes.enrich(r);
        assertThat(r).containsEntry("suggestedDeliveryDate","2026-10-17").containsEntry("suggestedFactoryDate","2026-10-28").containsEntry("forecastDeliveryDate","2026-10-21").doesNotContainKey("plannedMoldDeliveryDate").containsEntry("marketEligible",false);
    }
    @Test void passedBothPartsWithValidDatesIsRequiredForExplicitMarketConfirmation() {
        var r=row("MB冰盾");r.put("marketReadyDate","2026-10-21");assertThatThrownBy(()->MoldScheduleTypes.validate(Map.of(),r,List.of())).hasMessageContaining("均有效到厂");
        for(String p:List.of("pc","tpu")) {r.put(p+"AcceptanceStatus","passed");r.put(p+"FactoryArrivalDate","2026-10-20");r.put(p+"AcceptanceDate","2026-10-21");}
        assertThatCode(()->MoldScheduleTypes.validate(Map.of(),r,List.of())).doesNotThrowAnyException();r.put("marketReadyDate","2026-10-20");assertThatThrownBy(()->MoldScheduleTypes.validate(Map.of(),r,List.of())).hasMessageContaining("不得早于");
    }
    @Test void dateCorrectionsNeedReasonAndDoNotAddAModelOrBomWrite() {
        var c=new CollaborationTypes.CellChange("actualMexicoArrivalDate",json.valueToTree("2026-10-20"),json.valueToTree("2026-10-21"),null);
        assertThatThrownBy(()->MoldScheduleTypes.validate(Map.of("actualMexicoArrivalDate","2026-10-20"),Map.of("actualMexicoArrivalDate","2026-10-21"),List.of(c))).isInstanceOf(BusinessException.class).hasMessageContaining("更正已保存日期");
        var plan=new CollaborationTypes.CellChange("plannedMoldDeliveryDate",json.valueToTree("2026-10-20"),json.valueToTree("2026-10-21"),null);
        assertThatCode(()->MoldScheduleTypes.validate(Map.of("plannedMoldDeliveryDate","2026-10-20"),Map.of("plannedMoldDeliveryDate","2026-10-21"),List.of(plan))).doesNotThrowAnyException();
    }
    @Test void signedDatesUseTheSetAuthorityNotThePcTpuPartTable() {
        var f=CollaborationFields.field("mold_set","pcSignedDate");assertThat(CollaborationFields.partField(f)).isFalse();assertThat(f.group()).isEqualTo("mexico");
        assertThat(CollaborationFields.partField(CollaborationFields.field("mold_set","pcFactoryArrivalDate"))).isTrue();
        assertThat(CollaborationFields.MOLD).extracting(CollaborationFields.Field::key).doesNotHaveDuplicates();
    }
    @Test void overdueTasksDependOnConfirmedDueDatesNotFormulaSuggestionsOrProjectArchive() {
        var r=row("MB冰盾");MoldScheduleTypes.enrich(r);assertThat(MoldScheduleService.tasksFor(r,LocalDate.parse("2026-11-01"))).noneMatch(MoldScheduleService.Task::overdue);
        r.put("plannedMoldDeliveryDate","2026-10-15");r.put("projectStatus","archived");var tasks=MoldScheduleService.tasksFor(r,LocalDate.parse("2026-11-01"));assertThat(tasks).anySatisfy(t->{assertThat(t.taskKey()).isEqualTo("mold_complete");assertThat(t.overdue()).isTrue();});
    }
}
