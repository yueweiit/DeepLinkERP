import { describe, expect, it } from 'vitest'
import { acceptFinanceSave, editFinanceCell, financeValue, parseFinancePaste, previewFormula, previewBreakEvenQuantity, type FinanceDraft } from '../financeDrafts'
import type { FinanceRow } from '@/api/modules/development'
describe('shared finance drafts and formula preview', () => {
  it('keeps unknown distinct from zero and submits only actual changed fields', () => { const map = new Map<number,FinanceDraft>(); const row:FinanceRow = { budgetId:1,currencyCode:'CNY',moldCost:null }; editFinanceCell(map,1,row,'moldCost','0');expect(map.get(1)?.changes.get('moldCost')).toEqual({field:'moldCost',before:null,after:'0'});editFinanceCell(map,1,row,'moldCost',null);expect(map.size).toBe(0) })
  it('does not change the original baseline during a refresh or continuous editing', () => {
    const map = new Map<number,FinanceDraft>();const row:FinanceRow={expenseId:1,currencyCode:'CNY',declaredAmount:10}
    editFinanceCell(map,1,row,'declaredAmount','20');editFinanceCell(map,1,{...row,declaredAmount:30},'declaredAmount','25')
    expect(map.get(1)?.changes.get('declaredAmount')).toEqual({field:'declaredAmount',before:10,after:'25'})
    const submitted=[{...map.get(1)!.changes.get('declaredAmount')!}]
    editFinanceCell(map,1,row,'declaredAmount','26');editFinanceCell(map,1,row,'notes','not-submitted')
    acceptFinanceSave(map,1,submitted,{...row,declaredAmount:null})
    expect(map.get(1)?.changes.get('declaredAmount')).toEqual({field:'declaredAmount',before:null,after:'26'})
    expect(map.get(1)?.changes.get('notes')).toEqual({field:'notes',before:null,after:'not-submitted'})
    const next=[{...map.get(1)!.changes.get('declaredAmount')!}];editFinanceCell(map,1,row,'declaredAmount','27')
    acceptFinanceSave(map,1,next,{...row,declaredAmount:0})
    expect(map.get(1)?.changes.get('declaredAmount')).toEqual({field:'declaredAmount',before:0,after:'27'})
    acceptFinanceSave(map,1,[{...map.get(1)!.changes.get('declaredAmount')!}],null)
    expect(map.get(1)?.changes.has('declaredAmount')).toBe(false);expect(map.get(1)?.changes.has('notes')).toBe(true)
  })
  it('parses rectangular Excel regions without inferring sums or accepting negative declarations', () => { expect(parseFinancePaste('100\t0\r\n200\t\n')).toEqual([['100','0'],['200','']]);expect(financeValue('',true)).toBeNull();expect(financeValue('0',true)).toBe('0');expect(()=>financeValue('-1',true)).toThrow();expect(()=>financeValue('OK 5400',true)).toThrow() })
  it('matches the confirmed original sheet formula and keeps incomplete estimates unknown', () => { const row:FinanceRow={currencyCode:'CNY',calculationMode:'mold_formula',moldCost:14770,moldWeight:55,transportRate:74.68,fuelRate:33.18,customsCost:1000,salePrice:8,unitProductionCost:4.8};expect(previewFormula(row)).toBe(21702.3);expect(previewBreakEvenQuantity(row)).toBe(6782);expect(previewFormula({...row,moldCost:null})).toBeNull();expect(previewFormula({...row,moldCost:'invalid'})).toBeNull();expect(previewFormula({...row,calculationMode:'manual',budgetAmount:25000})).toBe(25000);expect(previewFormula({...row,calculationMode:'manual',budgetAmount:''})).toBeNull();expect(previewBreakEvenQuantity({...row,salePrice:4})).toBeNull() })
})
