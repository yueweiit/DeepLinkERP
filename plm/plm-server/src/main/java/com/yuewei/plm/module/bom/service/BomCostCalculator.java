package com.yuewei.plm.module.bom.service;

import com.yuewei.plm.module.bom.entity.ProductBomItem;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import java.math.BigDecimal;
import java.util.List;
import org.springframework.stereotype.Component;

@Component
public class BomCostCalculator {

    public Result calculate(
        List<ProductBomItem> items,
        String bomCurrency,
        BigDecimal processCost,
        BigDecimal packageCost,
        BigDecimal laborCost,
        BigDecimal toolingCost,
        BigDecimal otherCost
    ) {
        BigDecimal material = BigDecimal.ZERO;
        BigDecimal loss = BigDecimal.ZERO;
        for (ProductBomItem item : items) {
            if(item.getQuantity()!=null&&item.getQuantity().signum()>0&&item.getUnitCostSnapshot()==null)
                throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR,"物料单价未知，不能按零成本核算；请财务确认原币单价后重算（行 "+item.getLineNo()+"）");
            if(item.getQuantity()!=null&&item.getQuantity().signum()>0&&(item.getCurrencyCode()==null||item.getCurrencyCode().isBlank()||bomCurrency==null||!item.getCurrencyCode().trim().equalsIgnoreCase(bomCurrency.trim())))
                throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR,"物料原币未知或与 BOM 币种不一致，不能混加或自动换算；请财务核对（行 "+item.getLineNo()+"）");
            BigDecimal base = zero(item.getUnitCostSnapshot()).multiply(zero(item.getQuantity()));
            material = material.add(base);
            loss = loss.add(base.multiply(zero(item.getLossRate())));
        }
        BigDecimal total = material
            .add(loss)
            .add(zero(processCost))
            .add(zero(packageCost))
            .add(zero(laborCost))
            .add(zero(toolingCost))
            .add(zero(otherCost));
        return new Result(
            material, loss, zero(processCost), zero(packageCost), zero(laborCost),
            zero(toolingCost), zero(otherCost), total
        );
    }

    private BigDecimal zero(BigDecimal value) {
        return value == null ? BigDecimal.ZERO : value;
    }

    public record Result(
        BigDecimal materialCost,
        BigDecimal lossCost,
        BigDecimal processCost,
        BigDecimal packageCost,
        BigDecimal laborCost,
        BigDecimal toolingCost,
        BigDecimal otherCost,
        BigDecimal totalCost
    ) {
    }
}
