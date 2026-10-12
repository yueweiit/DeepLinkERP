import { createPinia, disposePinia, getActivePinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
const api = vi.hoisted(() => ({ saveFinanceRows: vi.fn() }))
vi.mock('@/api/modules/development', () => api)
import { useUserStore } from '../user'
import { useFinanceWorkspace } from '../financeWorkspace'
import { editFinanceCell } from '@/views/development/financeDrafts'
import type { FinanceResult, FinanceRow } from '@/api/modules/development'
const row: FinanceRow = { expenseId: 9, currencyCode: 'CNY', declaredAmount: null, notes: null }
beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); setActivePinia(createPinia()); useUserStore().token = 'first-test-session' })
afterEach(() => { const pinia=getActivePinia();if(pinia)disposePinia(pinia) })
function pending() {
  let complete!: (results: FinanceResult[]) => void
  api.saveFinanceRows.mockImplementationOnce(() => new Promise<FinanceResult[]>(resolve => { complete = resolve }))
  return (saved: FinanceRow) => complete([{ id: 9, status: 'saved', message: 'saved', conflicts: [], row: saved }])
}
describe('one finance workspace for all entry points', () => {
  it('single-flights saves while a late receipt retains subsequently edited cells and original unknown values', async () => {
    const workspace = useFinanceWorkspace(), ledger = workspace.forEntity('expense'), complete = pending()
    editFinanceCell(ledger.drafts, 9, row, 'declaredAmount', '20')
    const save = workspace.save('expense', '核对')
    expect(ledger.saving).toBe(true)
    editFinanceCell(ledger.drafts, 9, row, 'declaredAmount', '25')
    editFinanceCell(ledger.drafts, 9, row, 'notes', '新备注')
    await workspace.save('expense', '另一入口')
    expect(api.saveFinanceRows).toHaveBeenCalledTimes(1)
    expect(api.saveFinanceRows.mock.calls[0]![1][0].changes).toEqual([{ field: 'declaredAmount', before: null, after: '20' }])
    complete({ ...row, declaredAmount: 20, notes: '他人修改' }); await save
    expect(ledger.drafts.get(9)?.changes.get('declaredAmount')).toEqual({ field: 'declaredAmount', before: 20, after: '25' })
    editFinanceCell(ledger.drafts, 9, { ...row, notes: '他人修改' }, 'notes', '继续填写')
    expect(ledger.drafts.get(9)?.changes.get('notes')?.before).toBeNull()
    expect(ledger.revision).toBe(1)
    expect(ledger.saving).toBe(false)
    expect(workspace.forEntity('budget').drafts.size).toBe(0)
  })
  it('ignores an old account receipt after session replacement and does not unlock a new in-flight save', async () => {
    const workspace = useFinanceWorkspace(), ledger = workspace.forEntity('expense'), firstComplete = pending()
    editFinanceCell(ledger.drafts, 9, row, 'declaredAmount', '20')
    const first = workspace.save('expense', '旧会话')
    useUserStore().token = 'next-test-session'
    const secondComplete = pending()
    editFinanceCell(ledger.drafts, 9, row, 'declaredAmount', '0')
    const second = workspace.save('expense', '新会话')
    firstComplete({ ...row, declaredAmount: 20 }); expect(await first).toBeUndefined()
    expect(ledger.overrides.size).toBe(0)
    expect(ledger.saving).toBe(true)
    expect(ledger.drafts.get(9)?.changes.get('declaredAmount')?.after).toBe('0')
    secondComplete({ ...row, declaredAmount: 0 }); await second
    expect(ledger.overrides.get(9)?.declaredAmount).toBe(0)
    expect(ledger.drafts.size).toBe(0)
  })
})
