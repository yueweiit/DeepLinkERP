package com.yuewei.plm.module.collaboration;

import com.fasterxml.jackson.databind.JsonNode;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.ResolverStyle;
import java.util.*;

/** One field allowlist shared by authorisation, SQL updates and import validation. */
public final class CollaborationFields {
    public record Field(String key, String column, String label, String group, String kind, int maxLength) {}
    public static final List<String> GROUPS=List.of("market","engineering","logistics","mexico","production");
    public static final List<Field> ITEM=List.of(
        f("styleName","style_name","产品款式","market","required",255),
        f("productLineId","product_line_id","关联产品线","market","id",0),
        f("brand","brand","品牌","market","text",128),
        f("compatibleModels","compatible_models","兼容手机型号","market","required",512),
        f("phoneModelCode","phone_model_code","手机型号编码","market","code",20),
        f("phonePrice","phone_price","手机价格","market","money",0),
        f("priceCurrency","price_currency","价格币种","market","currency",12),
        f("salesPlatform","sales_platform","销售平台","market","text",512),
        f("referenceUrl","reference_url","参考链接","market","url",4000),
        f("notes","notes","市场备注","market","text",4000),
        f("pcTotal","pc_total","PC 半成品累计","production","count",0),
        f("tpuTotal","tpu_total","TPU 半成品累计","production","count",0),
        f("finishedTotal","finished_total","成品累计","production","count",0),
        f("productionNotes","production_notes","产量备注","production","text",4000));
    public static final List<Field> MOLD=java.util.stream.Stream.concat(List.of(
        f("setName","set_name","模具套名称","engineering","required",255),
        f("manufacturerName","manufacturer_name","制模厂家","engineering","text",255),
        f("ownerUserId","owner_user_id","模具负责人","engineering","id",0),
        f("openedDate","opened_date","开模日期","engineering","date",0),
        f("plannedMoldDeliveryDate","planned_mold_delivery_date","计划模具交付日期","engineering","date",0),
        f("pcStatus","status","PC 制作状态","engineering","part_status",0),
        f("tpuStatus","status","TPU 制作状态","engineering","part_status",0),
        f("pcMoldCodeId","product_mold_code_id","PC 模具编码","engineering","id",0),
        f("tpuMoldCodeId","product_mold_code_id","TPU 模具编码","engineering","id",0),
        f("actualShipDate","actual_ship_date","实际发模日期","logistics","date",0),
        f("plannedFactoryArrivalDate","planned_factory_arrival_date","计划到墨西哥工厂","logistics","date",0),
        f("actualMexicoArrivalDate","actual_mexico_arrival_date","实际抵达墨西哥","logistics","date",0),
        f("notes","notes","模具备注","engineering","text",4000),
        f("pcOriginalMoldCode","original_mold_code","PC 原模具编码","engineering","text",64),
        f("tpuOriginalMoldCode","original_mold_code","TPU 原模具编码","engineering","text",64),
        f("pcInventoryId","inventory_id","PC 历史库存资料ID","engineering","id",0),
        f("tpuInventoryId","inventory_id","TPU 历史库存资料ID","engineering","id",0),
        f("pcCurrentLocation","current_location","PC 当前位置","logistics","location",32),
        f("tpuCurrentLocation","current_location","TPU 当前位置","logistics","location",32),
        f("pcLocationDetail","location_detail","PC 具体位置","logistics","text",255),
        f("tpuLocationDetail","location_detail","TPU 具体位置","logistics","text",255),
        f("pcFactoryArrivalDate","factory_arrival_date","PC 实际到厂日期","mexico","date",0),
        f("tpuFactoryArrivalDate","factory_arrival_date","TPU 实际到厂日期","mexico","date",0),
        f("pcAcceptanceStatus","acceptance_status","PC 验收结果","mexico","acceptance",16),
        f("tpuAcceptanceStatus","acceptance_status","TPU 验收结果","mexico","acceptance",16),
        f("pcAcceptanceDate","acceptance_date","PC 验收日期","mexico","date",0),
        f("tpuAcceptanceDate","acceptance_date","TPU 验收日期","mexico","date",0),
        f("pcAcceptanceIssues","acceptance_issues","PC 验收问题说明","mexico","text",4000),
        f("tpuAcceptanceIssues","acceptance_issues","TPU 验收问题说明","mexico","text",4000)).stream(),MoldScheduleTypes.FIELDS.stream()).toList();
    public static boolean partField(Field f) {return (f.key.startsWith("pc")||f.key.startsWith("tpu"))&&!Set.of("pcSignedDate","tpuSignedDate").contains(f.key);}
    private static Field f(String k,String c,String l,String g,String t,int n) {return new Field(k,c,l,g,t,n);}
    private CollaborationFields() {}
    public static List<Field> fields(String entity) {
        if ("item".equals(entity)) return ITEM;
        if ("mold_set".equals(entity)) return MOLD;
        throw invalid("未知记录类型");
    }
    public static Field field(String entity,String key) {
        return fields(entity).stream().filter(f->f.key.equals(key)).findFirst().orElseThrow(()->invalid("不能修改字段："+key));
    }
    public static Object normalise(Field field, JsonNode node) {
        String text=node==null || node.isNull()?"":node.asText().trim();
        if (text.isEmpty()) {
            if (field.kind.equals("required")) throw invalid(field.label+"不能为空");
            return null;
        }
        try {
            return switch(field.kind) {
                case "count" -> { BigDecimal n=new BigDecimal(text); long v=n.longValueExact();
                    if(v<0 || v>9_007_199_254_740_991L) throw invalid(field.label+"须为非负整数"); yield v; }
                case "money" -> { BigDecimal n=new BigDecimal(text);
                    if(n.signum()<0 || n.precision()>16 || n.scale()>2) throw invalid("价格须为非负数字，最多两位小数"); yield n; }
                case "id" -> {long id=Long.parseLong(text); if(id<1) throw invalid("关联 ID 无效"); yield id;}
                case "date" -> parseDate(text);
                case "part_status" -> { if(!List.of("pending","making","ready").contains(text)) throw invalid("制作状态无效"); yield text; }
                case "acceptance" -> {String result=switch(text) {case "待验收" -> "pending";case "通过","验收通过" -> "passed";case "不通过","验收不通过" -> "failed";default -> text;};if(!List.of("pending","passed","failed").contains(result)) throw invalid("验收结果无效");yield result;}
                case "location" -> {String location=switch(text) {case "未知","unknown" -> null;case "中国制模厂" -> "china_maker";case "中国待发区" -> "china_dispatch";case "国际运输中" -> "in_transit";case "墨西哥待转运" -> "mexico_transit";case "墨西哥工厂" -> "mexico_factory";case "其他" -> "other";default -> text;};if(location!=null&&!List.of("china_maker","china_dispatch","in_transit","mexico_transit","mexico_factory","other").contains(location)) throw invalid("模具位置无效");yield location;}
                case "code" -> {if(!text.matches("[0-9]{4}")) throw invalid("手机型号编码须为四位字符串"); yield text;}
                case "currency" -> {String currency=text.toUpperCase(Locale.ROOT);
                    if(!Set.of("CNY","MXN","USD","EUR","UNKNOWN").contains(currency)) throw invalid("请选择价格币种"); yield currency;}
                case "url" -> {checkLength(field,text); for(String url:text.split("[\\s\\n]+")) {
                    java.net.URI u=java.net.URI.create(url);
                    if(!List.of("http","https").contains(u.getScheme()) || u.getHost()==null) throw invalid("参考链接只支持完整 HTTP/HTTPS 地址");
                } yield text;}
                default -> {checkLength(field,text); yield text;}
            };
        } catch(BusinessException e) {throw e;} catch(RuntimeException e) {throw invalid(field.label+"格式不正确");}
    }
    public static LocalDate parseDate(String text) {
        if(text==null || text.isBlank() || Set.of("暂无数据","无","--","-").contains(text.trim())) return null;
        for(String pattern:List.of("uuuu-MM-dd","d/M/uuuu","uuuu/M/d","uuuu年M月d日")) {
            try {return LocalDate.parse(text.trim(),DateTimeFormatter.ofPattern(pattern).withResolverStyle(ResolverStyle.STRICT));}
            catch(java.time.format.DateTimeParseException ignored) { }
        }
        throw invalid("日期须包含完整年月日，例如 2026-08-21 或 21/08/2026");
    }
    public static List<String> dateWarnings(Map<String,Object> row) {
        List<String> warnings=new ArrayList<>();
        checkOrder(row,"openedDate","plannedMoldDeliveryDate","计划交付早于开模日期",warnings);
        checkOrder(row,"openedDate","actualShipDate","实际发模早于开模日期",warnings);
        checkOrder(row,"actualShipDate","actualMexicoArrivalDate","抵达墨西哥早于实际发模",warnings);
        checkOrder(row,"plannedMoldDeliveryDate","plannedFactoryArrivalDate","计划到厂早于计划模具交付",warnings);
        checkOrder(row,"plannedFactoryArrivalDate","plannedAcceptanceDate","计划验收早于计划到厂",warnings);
        checkOrder(row,"plannedAcceptanceDate","plannedProductionDate","计划量产早于计划验收",warnings);
        checkOrder(row,"forecastDeliveryDate","forecastFactoryDate","预测到厂早于预测模具完成",warnings);
        checkOrder(row,"forecastFactoryDate","forecastAcceptanceDate","预测验收早于预测到厂",warnings);
        checkOrder(row,"forecastAcceptanceDate","forecastProductionDate","预测量产早于预测验收",warnings);
        checkOrder(row,"actualShipDate","actualPortArrivalDate","实际到港早于实际发模",warnings);
        checkOrder(row,"pcSignedDate","pcAcceptanceDate","PC 验收早于实际签收",warnings);
        checkOrder(row,"tpuSignedDate","tpuAcceptanceDate","TPU 验收早于实际签收",warnings);
        return warnings;
    }
    private static void checkOrder(Map<String,Object> r,String a,String b,String message,List<String> warnings) {
        if(r.get(a)!=null && r.get(b)!=null && parseDate(r.get(b).toString()).isBefore(parseDate(r.get(a).toString()))) warnings.add(message);
    }
    public static boolean same(Object a,Object b) {
        if(a==null || b==null) return a==b;
        if(a instanceof Number && b instanceof Number) return new BigDecimal(a.toString()).compareTo(new BigDecimal(b.toString()))==0;
        return a.toString().equals(b.toString());
    }
    /** Only explicit brand names at a word boundary, never guesses from SM/IP or marketing aliases. */
    public static String brandFromModel(String model) {
        if(model==null) return null;
        String name=model.trim();
        for(String brand:List.of("Apple","Samsung","Motorola","HONOR","Xiaomi","OPPO","ZTE","HUAWEI","vivo","realme","OnePlus","TECNO","Infinix","Nokia"))
            if(name.matches("(?i)^"+java.util.regex.Pattern.quote(brand)+"(?:[\\s:/-].*|$)")) return brand;
        return null;
    }
    private static void checkLength(Field f,String s) {if(s.length()>f.maxLength) throw invalid(f.label+"长度超出限制");}
    public static BusinessException invalid(String message) {return new BusinessException(ErrorCodeConstants.VALIDATION_ERROR,message);}
}
