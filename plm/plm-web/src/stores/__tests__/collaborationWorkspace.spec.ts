import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it } from 'vitest'
import { useCollaborationWorkspace } from '../collaborationWorkspace'
import { useUserStore } from '../user'
import type { CollaborationRow } from '@/types/collaboration'
describe('shared collaboration/mold session workspace',()=>{
  it('shares original-value drafts across entry points and revisions invalidate both caches',()=>{setActivePinia(createPinia());const a=useCollaborationWorkspace(),b=useCollaborationWorkspace();a.drafts.set({itemId:1,moldSetId:2,manufacturerName:null} as CollaborationRow,'manufacturerName','草稿');expect(b.drafts.value({itemId:1,moldSetId:2,manufacturerName:'刷新后的值'} as CollaborationRow,'manufacturerName')).toBe('草稿');expect(b.drafts.patches()[0].changes[0].before).toBeNull();a.changed();expect(b.revision).toBe(1)})
  it('clears drafts and signals cache invalidation synchronously on logout or session change',()=>{setActivePinia(createPinia());const u=useUserStore();u.token='first';const w=useCollaborationWorkspace();w.drafts.set({itemId:1,moldSetId:2} as CollaborationRow,'pcCurrentLocation','in_transit');u.token='second';expect(w.drafts.rows.size).toBe(0);expect(w.revision).toBe(1)})
})
