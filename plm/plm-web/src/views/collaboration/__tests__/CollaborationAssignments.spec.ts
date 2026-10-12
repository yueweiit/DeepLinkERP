import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus, { ElSelect } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
const api=vi.hoisted(()=>({getCollaborationAssignments:vi.fn(),saveCollaborationAssignments:vi.fn()}))
vi.mock('@/api/modules/collaboration',()=>api)
import CollaborationAssignments from '../components/CollaborationAssignments.vue'
const wrappers:ReturnType<typeof mount>[]=[]
const groups={market:[],engineering:[1],logistics:[],mexico:[],production:[]}
beforeEach(()=>{vi.clearAllMocks();api.getCollaborationAssignments.mockResolvedValue({groups,users:[{userId:1,username:'engineer01',displayName:'真实工程',allPermissions:false},{userId:2,username:'supplier01',displayName:'真实供应商',allPermissions:false}]});api.saveCollaborationAssignments.mockResolvedValue({groups:{...groups,engineering:[2]},users:[]})})
afterEach(()=>wrappers.splice(0).forEach(w=>w.unmount()))
describe('one collaboration assignment editor in both surfaces',()=>{
 it('uses the original value baseline when saving the system-page editor',async()=>{const w=mount(CollaborationAssignments,{props:{pageMode:true},global:{plugins:[ElementPlus]}});wrappers.push(w);await flushPromises();w.findAllComponents(ElSelect)[1].vm.$emit('update:modelValue',[2]);await flushPromises();await w.findAll('button').find(b=>b.text()==='保存职责')!.trigger('click');await flushPromises();expect(api.saveCollaborationAssignments).toHaveBeenCalledWith({...groups,engineering:[2]},groups);expect(w.emitted('saved')).toHaveLength(1)})
 it('loads the same editor lazily in the original dialog and retains rejected edits',async()=>{api.saveCollaborationAssignments.mockRejectedValue(new Error('conflict'));const w=mount(CollaborationAssignments,{props:{modelValue:false},global:{plugins:[ElementPlus]}});wrappers.push(w);await flushPromises();expect(api.getCollaborationAssignments).not.toHaveBeenCalled();await w.setProps({modelValue:true});await flushPromises();w.findAllComponents(ElSelect)[1].vm.$emit('update:modelValue',[2]);await flushPromises();await w.findAll('button').find(b=>b.text()==='保存职责')!.trigger('click');await flushPromises();expect(w.text()).toContain('职责已变化');expect(w.findAllComponents(ElSelect)[1].props('modelValue')).toEqual([2]);expect(w.emitted('saved')).toBeUndefined()})
})
