package com.yuewei.plm.module.project.service.impl;

import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.module.bom.service.BomLedgerService;
import com.yuewei.plm.module.development.DevelopmentFinanceService;
import com.yuewei.plm.module.development.DevelopmentTypes;
import com.yuewei.plm.module.project.dto.ProjectCostItemCreateDTO;
import com.yuewei.plm.module.project.dto.ProjectCostItemUpdateDTO;
import com.yuewei.plm.module.project.service.ProjectCostService;
import com.yuewei.plm.module.project.vo.ProjectCostItemVO;
import com.yuewei.plm.module.project.vo.ProjectCostSummaryVO;
import jakarta.servlet.http.HttpServletRequest;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.*;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

/** Compatibility adapter: old project routes delegate to the unified ledger/state machine.
 * Retain during the four-week pilot; remove only after callers and external traffic reach zero.
 */
@Service @RequiredArgsConstructor
public class ProjectCostServiceImpl implements ProjectCostService {
    private final DevelopmentFinanceService finance;
    private final BomLedgerService bomLedgerService;
    @Override public ProjectCostSummaryVO getSummary(Long projectId) {
        List<Map<String,Object>> items=finance.legacyItems(projectId);
        Map<String,Map<String,Object>> groups=new TreeMap<>();
        for(var item:items) if("confirmed".equals(item.get("state"))&&"manual".equals(item.get("sourceSystem"))) {
            var group=groups.computeIfAbsent(item.get("currencyCode").toString(),c->{var m=new LinkedHashMap<String,Object>();m.put("currencyCode",c);m.put("moldCost",BigDecimal.ZERO);m.put("otherCost",BigDecimal.ZERO);m.put("unknownCount",0);return m;});
            Object amount=item.get("declaredAmount");if(amount==null) {group.put("unknownCount",((Number)group.get("unknownCount")).intValue()+1);continue;}
            String field="mold".equals(item.get("expenseCategory"))?"moldCost":"otherCost";group.put(field,((BigDecimal)group.get(field)).add(new BigDecimal(amount.toString())));
        }
        groups.values().forEach(g->g.put("totalCost",((BigDecimal)g.get("moldCost")).add((BigDecimal)g.get("otherCost"))));
        var bom=bomLedgerService.getSummary(projectId);var only=groups.size()==1?groups.values().iterator().next():null;
        boolean known=only!=null&&((Number)only.get("unknownCount")).intValue()==0;
        return ProjectCostSummaryVO.builder().projectId(projectId).productId(projectId).bomCost(bom==null?null:bom.getCurrentBomSkuUnitCost())
            .rdCost(BigDecimal.ZERO).moldCost(known?(BigDecimal)only.get("moldCost"):null).otherCost(known?(BigDecimal)only.get("otherCost"):null)
            .totalCost(known?(BigDecimal)only.get("totalCost"):null).currencyCode(only==null?"MULTI":only.get("currencyCode").toString())
            .currencyGroups(new ArrayList<>(groups.values())).summaryNote("BOM为单位成本参考，不计入专项实际费用；旧颜色项目费用须在开发费用归集核对共享归属")
            .manualItemCount(items.size()).confirmedManualItemCount((int)items.stream().filter(i->"confirmed".equals(i.get("state"))).count()).build();
    }
    @Override public List<ProjectCostItemVO> listItems(Long id){return finance.legacyItems(id).stream().map(this::vo).toList();}
    @Override @org.springframework.transaction.annotation.Transactional public ProjectCostItemVO createItem(Long id,ProjectCostItemCreateDTO d,HttpServletRequest r){
        var created=finance.createExpense(new DevelopmentTypes.CreateExpense(d.getCostName(),null,null,null,null,d.getCurrencyCode()),id,r);
        return result(finance.legacyUpdate(id,((Number)created.get("expenseId")).longValue(),values(d.getCostCategory(),d.getCostName(),d.getAmount(),d.getSupplierName(),d.getOccurredAt(),d.getRemark()),date(created,"updatedAt"),r));
    }
    @Override public ProjectCostItemVO updateItem(Long id,Long costId,ProjectCostItemUpdateDTO d,HttpServletRequest r){return result(finance.legacyUpdate(id,costId,values(d.getCostCategory(),d.getCostName(),d.getAmount(),d.getSupplierName(),d.getOccurredAt(),d.getRemark()),d.getBeforeUpdatedAt(),r));}
    @Override public ProjectCostItemVO confirmItem(Long id,Long costId,HttpServletRequest r){return result(finance.transition(id,costId,"confirmed",r));}
    @Override public ProjectCostItemVO voidItem(Long id,Long costId,HttpServletRequest r){return result(finance.transition(id,costId,"void",r));}
    private Map<String,Object> values(String category,String name,BigDecimal amount,String supplier,LocalDateTime date,String notes){var map=new LinkedHashMap<String,Object>();map.put("expenseCategory",category);map.put("description",name);map.put("declaredAmount",amount);map.put("supplierName",supplier);map.put("occurredAt",date);map.put("notes",notes);return map;}
    private ProjectCostItemVO result(DevelopmentTypes.Result result){if(!result.status().equals("saved"))throw new BusinessException(result.status().equals("forbidden")?40103:40001,result.message());return vo(result.row());}
    private BigDecimal amount(Map<String,Object> row,String key){return row.get(key)==null?null:new BigDecimal(row.get(key).toString());}
    private LocalDateTime date(Map<String,Object> row,String key){if(row.get(key)==null)return null;try{return LocalDateTime.parse(row.get(key).toString());}catch(Exception e){return null;}}
    private ProjectCostItemVO vo(Map<String,Object> row){return ProjectCostItemVO.builder().projectCostItemId(((Number)row.get("expenseId")).longValue()).productId((Long)row.get("productId"))
        .costCategory((String)row.get("expenseCategory")).costCategoryName("mold".equals(row.get("expenseCategory"))?"模具成本":"其他成本").costName((String)row.get("description"))
        .amount(amount(row,"declaredAmount")).currencyCode((String)row.get("currencyCode")).supplierName((String)row.get("supplierName")).occurredAt(date(row,"occurredAt"))
        .status((String)row.get("state")).statusName(switch(row.get("state").toString()){case "confirmed"->"已确认";case "void"->"已作废";default->"草稿";})
        .confirmedAt(date(row,"confirmedAt")).confirmedBy((String)row.get("confirmedBy")).voidedAt(date(row,"voidedAt")).voidedBy((String)row.get("voidedBy"))
        .remark((String)row.get("notes")).createdAt(date(row,"createdAt")).createdBy((String)row.get("createdBy")).updatedAt(date(row,"updatedAt")).updatedBy((String)row.get("updatedBy")).build();}
}
