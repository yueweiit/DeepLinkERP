package com.yuewei.plm.module.bom.service;

import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.module.bom.dto.ProductBomItemDTO;
import com.yuewei.plm.module.bom.entity.ProductBomItem;
import java.math.BigDecimal;
import java.util.Objects;

/** The two BOM editors share one amount policy; null means unknown, not a free material. */
public final class BomAmountPolicy {
    private BomAmountPolicy() {}

    public static void apply(ProductBomItemDTO dto,ProductBomItem target,ProductBomItem source,
                             boolean canWrite,String newItemCurrency) {
        if(!canWrite&&(dto.getUnitCost()!=null||dto.getLineCost()!=null||text(dto.getCurrencyCode())))
            throw new BusinessException(40103,"没有权限：finance:write；请仅提交用量等非金额字段");
        if((dto.getUnitCost()!=null&&dto.getUnitCost().signum()<0)||(dto.getLineCost()!=null&&dto.getLineCost().signum()<0))
            throw new BusinessException(ErrorCodeConstants.VALIDATION_ERROR,"BOM 明细单价和单个成本不能为负数");
        // Read every original before mutating: direct-item updates use the same object as source/target.
        BigDecimal oldUnit=source==null?null:source.getUnitCostSnapshot();
        BigDecimal oldLine=source==null?null:source.getLineCostSnapshot();
        BigDecimal oldQuantity=source==null?null:source.getQuantity();
        String oldCurrency=source==null?null:source.getCurrencyCode();
        BigDecimal unit=canWrite&&dto.getUnitCost()!=null?dto.getUnitCost():oldUnit;
        BigDecimal line;
        if(canWrite&&dto.getLineCost()!=null)line=dto.getLineCost();
        else if(oldLine!=null&&same(oldQuantity,dto.getQuantity())&&same(oldUnit,unit))line=oldLine;
        else line=unit==null||dto.getQuantity()==null?null:dto.getQuantity().multiply(unit);
        String currency=canWrite&&text(dto.getCurrencyCode())?dto.getCurrencyCode().trim():
            source!=null?oldCurrency:canWrite?newItemCurrency:null;
        target.setUnitCostSnapshot(unit);target.setLineCostSnapshot(line);target.setCurrencyCode(currency);
    }

    public static boolean priced(ProductBomItem item){return item.getUnitCostSnapshot()!=null||item.getLineCostSnapshot()!=null;}
    private static boolean text(String value){return value!=null&&!value.isBlank();}
    private static boolean same(BigDecimal first,BigDecimal second){return first==null||second==null?Objects.equals(first,second):first.compareTo(second)==0;}
}
