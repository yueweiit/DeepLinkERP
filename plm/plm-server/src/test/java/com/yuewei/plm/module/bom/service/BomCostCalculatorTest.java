package com.yuewei.plm.module.bom.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.yuewei.plm.module.bom.entity.ProductBomItem;
import java.math.BigDecimal;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.core.annotation.AnnotationUtils;
import org.springframework.stereotype.Component;

class BomCostCalculatorTest {

    @Test
    void isRegisteredAsSpringBeanForWorkflowInjection() {
        assertThat(AnnotationUtils.findAnnotation(BomCostCalculator.class, Component.class)).isNotNull();
    }

    @Test
    void separatesMaterialAndLossAndBuildsRouteTotal() {
        ProductBomItem item = new ProductBomItem();
        item.setQuantity(new BigDecimal("2"));
        item.setUnitCostSnapshot(new BigDecimal("10"));
        item.setCurrencyCode("CNY");
        item.setLossRate(new BigDecimal("0.05"));

        BomCostCalculator.Result result = new BomCostCalculator().calculate(
            List.of(item),
            "CNY",
            new BigDecimal("3"),
            new BigDecimal("2"),
            BigDecimal.ONE,
            BigDecimal.ZERO,
            new BigDecimal("0.50")
        );

        assertThat(result.materialCost()).isEqualByComparingTo("20");
        assertThat(result.lossCost()).isEqualByComparingTo("1");
        assertThat(result.totalCost()).isEqualByComparingTo("27.50");
    }

    @Test
    void unknownMaterialPriceCannotBeCostedAsZeroButExplicitZeroAndNoMaterialsAreValid() {
        var item=new ProductBomItem();item.setLineNo(7);item.setQuantity(BigDecimal.ONE);var calculator=new BomCostCalculator();
        assertThatThrownBy(()->calculator.calculate(List.of(item),"CNY",null,null,null,null,null)).hasMessageContaining("物料单价未知").hasMessageContaining("行 7");
        item.setUnitCostSnapshot(BigDecimal.ZERO);item.setCurrencyCode("CNY");assertThat(calculator.calculate(List.of(item),"CNY",null,null,null,null,null).totalCost()).isZero();
        assertThat(calculator.calculate(List.of(),"CNY",new BigDecimal("3"),null,null,null,null).totalCost()).isEqualByComparingTo("3");
    }

    @Test
    void nullOptionalCostsAreTreatedAsZero() {
        ProductBomItem item = new ProductBomItem();
        item.setQuantity(BigDecimal.ONE);
        item.setUnitCostSnapshot(new BigDecimal("4.25"));
        item.setCurrencyCode("CNY");
        item.setLossRate(null);

        BomCostCalculator.Result result = new BomCostCalculator().calculate(
            List.of(item), "CNY", null, null, null, null, null
        );

        assertThat(result.totalCost()).isEqualByComparingTo("4.25");
    }

    @Test void originalCurrenciesCannotBeMixedOrGuessedWithoutAnExplicitConversion() {
        var item=new ProductBomItem();item.setLineNo(8);item.setQuantity(BigDecimal.ONE);item.setUnitCostSnapshot(BigDecimal.TEN);item.setCurrencyCode("USD");var calculator=new BomCostCalculator();
        assertThatThrownBy(()->calculator.calculate(List.of(item),"CNY",null,null,null,null,null)).hasMessageContaining("币种不一致");
        item.setCurrencyCode(null);assertThatThrownBy(()->calculator.calculate(List.of(item),"CNY",null,null,null,null,null)).hasMessageContaining("原币未知");
        item.setCurrencyCode("CNY");assertThat(calculator.calculate(List.of(item),"CNY",null,null,null,null,null).totalCost()).isEqualByComparingTo("10");
    }
}
