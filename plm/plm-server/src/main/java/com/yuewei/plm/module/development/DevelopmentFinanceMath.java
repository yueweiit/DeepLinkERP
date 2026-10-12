package com.yuewei.plm.module.development;

import com.fasterxml.jackson.databind.JsonNode;
import com.yuewei.plm.common.exception.BusinessException;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.*;

public final class DevelopmentFinanceMath {
    public static final BigDecimal TRANSPORT_RATE=new BigDecimal("74.68");
    public static final BigDecimal FUEL_RATE=new BigDecimal("33.18");
    /** The same nullable formula used by SQL row summaries; alias b is code-owned. */
    public static final String SQL_TOTAL="case when b.calculation_mode='manual' then b.budget_amount when b.mold_cost is not null and b.mold_weight is not null and b.transport_rate is not null and b.fuel_rate is not null and b.customs_cost is not null then b.mold_cost+round(b.mold_weight*b.transport_rate,2)+round(b.mold_weight*b.fuel_rate,2)+b.customs_cost end";
    private DevelopmentFinanceMath() {}
    public static BusinessException invalid(String message) {return new BusinessException(40001,message);}
    public static BigDecimal decimal(Object value) {return value==null?null:new BigDecimal(value.toString());}
    public static BigDecimal multiply(Object a,Object b) {return a==null||b==null?null:decimal(a).multiply(decimal(b)).setScale(2,RoundingMode.HALF_UP);}
    public static BigDecimal total(Map<String,Object> row) {
        if("manual".equals(row.get("calculationMode"))) return decimal(row.get("budgetAmount"));
        Object mold=row.get("moldCost"),customs=row.get("customsCost");
        BigDecimal transport=multiply(row.get("moldWeight"),row.get("transportRate")),fuel=multiply(row.get("moldWeight"),row.get("fuelRate"));
        return mold==null||customs==null||transport==null||fuel==null?null:decimal(mold).add(decimal(customs)).add(transport).add(fuel).setScale(2,RoundingMode.HALF_UP);
    }
    public static void calculate(Map<String,Object> row) {
        if(row.containsKey("budgetKind")) {
            row.put("transportCost",multiply(row.get("moldWeight"),row.get("transportRate")));
            row.put("fuelCost",multiply(row.get("moldWeight"),row.get("fuelRate")));
            BigDecimal total=total(row);row.put("calculatedTotal",total);
            BigDecimal sale=decimal(row.get("salePrice")),unit=decimal(row.get("unitProductionCost"));
            BigDecimal margin=sale==null||unit==null?null:sale.subtract(unit);row.put("unitMargin",margin);
            row.put("breakEvenQuantity",total==null||margin==null||margin.signum()<=0?null:total.divide(margin,0,RoundingMode.CEILING));
            row.put("breakEvenWarning",margin!=null&&margin.signum()<=0?"单件利润不为正，无法回本":null);
        }
    }
    public static Object amount(JsonNode node,int scale,boolean signed) {
        if(node==null||node.isNull()||node.asText().isBlank()) return null;
        try {BigDecimal value=new BigDecimal(node.asText());if((!signed&&value.signum()<0)||value.scale()>scale||value.precision()>18) throw invalid("金额/重量超出范围或精度");return value;}
        catch(NumberFormatException ex) {throw invalid("请填写数字，未知请留空；零是已确认零值");}
    }
    public static boolean same(Object a,Object b) {
        if(a==null||b==null) return a==b;
        if(a instanceof Number&&b instanceof Number) return decimal(a).compareTo(decimal(b))==0;
        return a.toString().equals(b.toString());
    }
}
