package com.yuewei.plm.module.collaboration;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.*;
import java.time.LocalDate;
import java.util.*;
import lombok.Data;
import static com.yuewei.plm.module.collaboration.CollaborationFields.*;

/** Schedule policy extends the existing field registry and save engine; no second ledger. */
public final class MoldScheduleTypes {
    private MoldScheduleTypes() {}
    @Data public static class Query {
        @Min(1) private int page=1;
        @Min(1) @Max(100) private int size=50;
        @Size(max=128) private String keyword;
        private Long productLineId;
        private Long moldSetId;
        private boolean mineOnly;
        private boolean overdueOnly;
        @Pattern(regexp="pending|making|ready|shipped|mexico_arrived|partially_arrived|awaiting_acceptance|partially_accepted|acceptance_failed|delivered|market_ready") private String status;
    }
    public record ConfirmPlan(@NotNull Map<String,JsonNode> before,@NotBlank @Size(max=2000) String reason) {}
    private static Field f(String key,String col,String label,String group,String kind) {return new Field(key,col,label,group,kind,kind.equals("text")?4000:0);}
    public static final List<Field> FIELDS=List.of(
        f("planStartDate","plan_start_date","计划开模日期","engineering","date"),
        f("manufacturingDays","manufacturing_days","模具制作天数","engineering","count"),
        f("holidayDays","holiday_days","法定假期天数","engineering","count"),
        f("extraDays","extra_days","累计额外天数","engineering","count"),
        f("forecastDeliveryDate","forecast_delivery_date","当前预测完成日期","engineering","date"),
        f("forecastFactoryDate","forecast_factory_date","当前预测到厂日期","logistics","date"),
        f("forecastAcceptanceDate","forecast_acceptance_date","当前预测验收日期","mexico","date"),
        f("forecastProductionDate","forecast_production_date","当前预测量产日期","mexico","date"),
        f("plannedAcceptanceDate","planned_acceptance_date","确认计划验收日期","mexico","date"),
        f("plannedProductionDate","planned_production_date","确认计划量产日期","mexico","date"),
        f("actualPortArrivalDate","actual_port_arrival_date","实际到港日期","logistics","date"),
        f("pcSignedDate","pc_signed_date","PC 实际签收日期","mexico","date"),
        f("tpuSignedDate","tpu_signed_date","TPU 实际签收日期","mexico","date"),
        f("actualSupplierTrialDate","actual_supplier_trial_date","中国制模试模日期","engineering","date"),
        f("actualTrialDate","actual_trial_date","墨西哥实际试模日期","mexico","date"),
        f("actualProductionDate","actual_production_date","墨西哥实际量产日期","mexico","date"),
        f("marketReadyDate","market_ready_date","上市确认日期","mexico","date"),
        f("logisticsOwnerUserId","logistics_owner_user_id","物流负责人ID","logistics","id"),
        f("mexicoOwnerUserId","mexico_owner_user_id","墨西哥验收负责人ID","mexico","id"),
        f("productionOwnerUserId","production_owner_user_id","试模量产负责人ID","mexico","id"),
        f("scheduleNotes","schedule_notes","排程备注","engineering","text"));
    public static final List<String> PLAN_KEYS=List.of("planStartDate","openedDate","manufacturingDays","holidayDays","extraDays","plannedMoldDeliveryDate","plannedFactoryArrivalDate","plannedAcceptanceDate","plannedProductionDate");
    private static final Set<String> ACTUAL_DATE_KEYS=Set.of("openedDate","actualShipDate","actualMexicoArrivalDate","actualPortArrivalDate","pcSignedDate","tpuSignedDate","pcFactoryArrivalDate","tpuFactoryArrivalDate","pcAcceptanceDate","tpuAcceptanceDate","actualSupplierTrialDate","actualTrialDate","actualProductionDate","marketReadyDate");
    public static final Map<String,Integer> STYLE_DAYS=Map.ofEntries(
        Map.entry("MB冰盾",12),Map.entry("MG金刚甲",12),Map.entry("MDN幻甲",12),Map.entry("MWV薇武士",12),
        Map.entry("MBA亮甲2.0",14),Map.entry("MBD圣殿",14),Map.entry("MHA超队",13),Map.entry("MFB骑士2.0",14),
        Map.entry("MFA骑士1.0",14),Map.entry("MG金刚透甲",12),Map.entry("MDN幻甲-磨砂",12));
    public static Integer defaultDays(String style) {return STYLE_DAYS.get(style==null?"":style.trim());}
    static LocalDate date(Object value) {return value==null?null:parseDate(value.toString());}
    static LocalDate plus(LocalDate value,int days) {return value==null?null:value.plusDays(days);}
    static void putDate(Map<String,Object> row,String key,LocalDate value) {row.put(key,value==null?null:value.toString());}
    public static void enrich(Map<String,Object> row) {
        Integer days=row.get("manufacturingDays")==null?defaultDays(Objects.toString(row.get("styleName"),"")):Integer.valueOf(((Number)row.get("manufacturingDays")).intValue());
        row.put("defaultManufacturingDays",defaultDays(Objects.toString(row.get("styleName"),"")));
        LocalDate start=date(row.get("openedDate")!=null?row.get("openedDate"):row.get("planStartDate"));
        int extra=((Number)row.getOrDefault("extraDays",0)).intValue(),holiday=((Number)row.getOrDefault("holidayDays",0)).intValue();
        LocalDate suggested=days==null?null:plus(start,days+holiday+extra);
        putDate(row,"suggestedDeliveryDate",suggested);
        LocalDate delivery=date(row.get("forecastDeliveryDate")!=null?row.get("forecastDeliveryDate"):row.get("plannedMoldDeliveryDate"));
        if(delivery==null) delivery=suggested;
        putDate(row,"suggestedFactoryDate",plus(delivery,7));
        LocalDate factory=date(row.get("forecastFactoryDate")!=null?row.get("forecastFactoryDate"):row.get("plannedFactoryArrivalDate"));
        if(factory==null) factory=plus(delivery,7);
        putDate(row,"suggestedAcceptanceDate",plus(factory,1));
        LocalDate acceptance=date(row.get("forecastAcceptanceDate")!=null?row.get("forecastAcceptanceDate"):row.get("plannedAcceptanceDate"));
        if(acceptance==null) acceptance=plus(factory,1);
        putDate(row,"suggestedProductionDate",plus(acceptance,3));
        row.put("marketEligible",marketEligible(row));
        row.put("scheduleStatus",row.get("marketReadyDate")!=null?"market_ready":row.get("deliveryStatus"));
        row.put("suggestionOnly",true);
    }
    public static boolean marketEligible(Map<String,Object> row) {
        for(String p:List.of("pc","tpu")) {
            LocalDate arrival=date(row.get(p+"FactoryArrivalDate")),acceptance=date(row.get(p+"AcceptanceDate"));
            if(!"passed".equals(row.get(p+"AcceptanceStatus"))||arrival==null||acceptance==null||acceptance.isBefore(arrival)) return false;
        }
        return true;
    }
    public static void validate(Map<String,Object> current,Map<String,Object> next,List<CollaborationTypes.CellChange> changes) {
        for(String key:List.of("manufacturingDays","holidayDays","extraDays")) {
            Object n=next.get(key);if(n!=null&&(((Number)n).longValue()>365||key.equals("manufacturingDays")&&((Number)n).longValue()<1)) throw invalid("制作、假期和额外天数须在有效范围内（最多 365）");
        }
        for(CollaborationTypes.CellChange change:changes) {
            Field field=field("mold_set",change.field());
            if(ACTUAL_DATE_KEYS.contains(field.key())&&current.get(field.key())!=null&&!same(current.get(field.key()),next.get(field.key()))&&(change.reason()==null||change.reason().isBlank()))
                throw invalid("更正已保存日期须填写原因："+field.label());
        }
        if(next.get("marketReadyDate")!=null) {
            if(!marketEligible(next)) throw invalid("PC、TPU 均有效到厂并验收通过后才可确认上市；抵墨或项目归档不能代替验收");
            LocalDate last=date(next.get("pcAcceptanceDate")).isAfter(date(next.get("tpuAcceptanceDate")))?date(next.get("pcAcceptanceDate")):date(next.get("tpuAcceptanceDate"));
            if(date(next.get("marketReadyDate")).isBefore(last)) throw invalid("上市确认日期不得早于两部件验收日期");
        }
        if(next.get("actualTrialDate")!=null&&next.get("actualProductionDate")!=null&&date(next.get("actualProductionDate")).isBefore(date(next.get("actualTrialDate")))) throw invalid("实际量产日期不得早于实际试模日期");
    }
}
