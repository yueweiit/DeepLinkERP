import { defineStore } from 'pinia'
import { onScopeDispose, reactive, watch } from 'vue'
import { saveFinanceRows, type FinanceEntity, type FinancePatch, type FinanceRow } from '@/api/modules/development'
import { acceptFinanceSave, type FinanceDraft } from '@/views/development/financeDrafts'
import { useUserStore } from './user'

/** One session workspace for the same ledger in project details and standalone pages. */
export const useFinanceWorkspace = defineStore('finance-workspace', () => {
  const user = useUserStore()
  const state = () => ({ drafts: new Map<number, FinanceDraft>(), overrides: new Map<number, FinanceRow>(), revision: 0, saving: false })
  const ledgers = reactive({ budget: state(), expense: state() })
  let sessionEpoch = 0
  function clear() {
    sessionEpoch++
    for (const ledger of Object.values(ledgers)) {
      ledger.drafts.clear()
      ledger.overrides.clear()
      ledger.saving = false
      ledger.revision++
    }
  }
  watch(() => user.token, clear, { flush: 'sync' })
  async function save(entity: FinanceEntity, reason: string) {
    const ledger = ledgers[entity]
    if (ledger.saving || !user.token || !ledger.drafts.size) return
    const epoch = sessionEpoch
    const rows: FinancePatch[] = [...ledger.drafts].map(([id, draft]) => ({ id, reason, changes: [...draft.changes.values()].map(change => ({ ...change })) }))
    const submitted = new Map(rows.map(row => [row.id, row.changes]))
    ledger.saving = true
    try {
      const results = await saveFinanceRows(entity, rows)
      if (epoch !== sessionEpoch) return
      for (const result of results) {
        if (result.status === 'saved') {
          acceptFinanceSave(ledger.drafts, result.id, submitted.get(result.id) || [], result.row)
          if (result.row) ledger.overrides.set(result.id, result.row)
        } else {
          const draft = ledger.drafts.get(result.id)
          if (draft) draft.error = result.message
        }
      }
      if (results.some(result => result.status === 'saved')) ledger.revision++
      return results
    } finally { if (epoch === sessionEpoch) ledger.saving = false }
  }
  function unload(event: BeforeUnloadEvent) {
    if (Object.values(ledgers).some(ledger => ledger.drafts.size)) {
      event.preventDefault()
      event.returnValue = ''
    }
  }
  window.addEventListener('beforeunload', unload)
  onScopeDispose(() => window.removeEventListener('beforeunload', unload))
  return { forEntity: (entity: FinanceEntity) => ledgers[entity], save }
})
