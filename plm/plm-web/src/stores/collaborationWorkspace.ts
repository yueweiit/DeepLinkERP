import { defineStore } from 'pinia'
import { reactive, ref, watch } from 'vue'
import { CollaborationDrafts } from '@/utils/collaboration'
import { useUserStore } from './user'

/** Same physical records and original-value drafts across both entry points, session-only. */
export const useCollaborationWorkspace = defineStore('collaboration-workspace', () => {
  const user = useUserStore()
  const drafts = reactive(new CollaborationDrafts())
  const revision = ref(0)
  function changed() { revision.value++ }
  watch(() => user.token, () => { drafts.clear(); changed() }, { flush: 'sync' })
  return { drafts, revision, changed }
})
