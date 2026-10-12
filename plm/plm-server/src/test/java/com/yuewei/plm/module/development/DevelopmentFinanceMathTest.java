package com.yuewei.plm.module.development;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigDecimal;
import java.util.*;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

class DevelopmentFinanceMathTest {
    @Test void originalWorkbookRatesAndCeilingPaybackRemainInvestmentNotUnitCost() {
        Map<String,Object> row=new LinkedHashMap<>(Map.of("budgetKind","platform","calculationMode","mold_formula","moldCost",14770,"moldWeight",55,"transportRate","74.68","fuelRate","33.18","customsCost",1000,"salePrice",8,"unitProductionCost","4.8"));
        DevelopmentFinanceMath.calculate(row);
        assertThat(row.get("transportCost")).isEqualTo(new BigDecimal("4107.40"));assertThat(row.get("fuelCost")).isEqualTo(new BigDecimal("1824.90"));assertThat(row.get("calculatedTotal")).isEqualTo(new BigDecimal("21702.30"));assertThat(row.get("breakEvenQuantity")).isEqualTo(new BigDecimal("6782"));
    }
    @Test void unknownZeroAndNonpositiveMarginHaveDifferentMeanings() {
        Map<String,Object> row=new LinkedHashMap<>(Map.of("budgetKind","mold","calculationMode","mold_formula","moldCost",0,"moldWeight",0,"transportRate",0,"fuelRate",0,"customsCost",0,"salePrice",0,"unitProductionCost",0));
        DevelopmentFinanceMath.calculate(row);assertThat(row.get("calculatedTotal")).isEqualTo(new BigDecimal("0.00"));assertThat(row.get("breakEvenQuantity")).isNull();assertThat(row.get("breakEvenWarning")).isNotNull();row.put("moldCost",null);DevelopmentFinanceMath.calculate(row);assertThat(row.get("calculatedTotal")).isNull();
    }
    @Test void manualBudgetDoesNotCombineFormulaAndParentAmounts() {
        Map<String,Object> row=new LinkedHashMap<>(Map.of("budgetKind","platform","calculationMode","manual","budgetAmount",25000,"moldCost",14770));assertThat(DevelopmentFinanceMath.total(row)).isEqualByComparingTo("25000");row.put("budgetAmount",null);assertThat(DevelopmentFinanceMath.total(row)).isNull();
    }
    @Test void signedAmountsAreReservedForErpReversals() {
        var json=new ObjectMapper();assertThatThrownBy(()->DevelopmentFinanceMath.amount(json.valueToTree(-100),2,false)).hasMessageContaining("范围");assertThat(DevelopmentFinanceMath.amount(json.valueToTree(-100),2,true)).isEqualTo(new BigDecimal("-100"));assertThat(DevelopmentFinanceMath.amount(json.nullNode(),2,false)).isNull();assertThat(DevelopmentFinanceMath.amount(json.valueToTree(0),2,false)).isEqualTo(BigDecimal.ZERO);
    }
}
