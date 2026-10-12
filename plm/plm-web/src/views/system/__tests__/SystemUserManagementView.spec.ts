import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus, { ElCheckbox, ElCheckboxGroup, ElInput, ElSelect, ElTag } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { PilotUser } from '@/types/pilot'
const api=vi.hoisted(()=>({getSystemUsers:vi.fn(),getSystemRoles:vi.fn(),saveSystemUser:vi.fn(),getSystemScopeOptions:vi.fn()}))
vi.mock('@/api/modules/system',()=>api)
vi.mock('@/components/FixedTableViewport/index.vue',()=>({default:{template:'<div><slot :table-height="400" /></div>'}}))
import SystemUserManagementView from '../SystemUserManagementView.vue'
const wrappers:ReturnType<typeof mount>[]=[]
const financeUser:PilotUser={userId:10,username:'finance01',displayName:'财务负责人',departmentName:'财务',status:'active',allPermissions:false,roleCode:'finance',allObjects:true,dingtalkUserId:'',permissions:['finance:read','finance:write','finance:export'],fieldGroups:[],scopes:[{entityType:'file',entityId:99}],version:7}
beforeEach(()=>{vi.clearAllMocks();api.getSystemUsers.mockResolvedValue([financeUser]);api.getSystemRoles.mockResolvedValue([{roleCode:'administrator',permissions:['*']},{roleCode:'finance',permissions:['finance:read','finance:write','finance:confirm','finance:export']}]);api.saveSystemUser.mockResolvedValue({saved:true})})
afterEach(()=>{wrappers.splice(0).forEach(w=>w.unmount())})
describe('existing system route now manages real accounts',()=>{
 it('shows administrator grants as fixed and restores independently editable grants after changing roles',async()=>{
  const w=mount(SystemUserManagementView,{global:{plugins:[ElementPlus]}});wrappers.push(w);await flushPromises();expect(w.text()).toContain('财务负责人')
  await w.findAll('button').find(b=>b.text()==='编辑 / 授权')!.trigger('click');await flushPromises()
  const role=w.findAllComponents(ElSelect)[0]
  role.vm.$emit('update:modelValue','administrator');role.vm.$emit('change','administrator');await flushPromises()
  expect(w.text()).toContain('管理员拥有全部对象、所有字段、全部金额操作及账号配置权限；要收权请先切换为其他固定角色。')
  expect(w.findAllComponents(ElCheckbox)[0].props()).toMatchObject({modelValue:true,disabled:true})
  expect(w.findAllComponents(ElCheckboxGroup).map(g=>g.props())).toEqual(expect.arrayContaining([expect.objectContaining({modelValue:['*'],disabled:true}),expect.objectContaining({modelValue:['market','engineering','logistics','mexico','production'],disabled:true})]))
  expect(w.findAllComponents(ElSelect).slice(2).every(s=>s.props('disabled'))).toBe(true)
  expect(w.findAllComponents(ElInput).find(i=>i.props('placeholder')==='搜索名称或编码')!.props('disabled')).toBe(true)
  for(const label of ['查询','加入授权'])expect(w.findAll('button').find(b=>b.text()===label)!.attributes('disabled')).toBeDefined()
  expect(w.findComponent(ElTag).props('closable')).toBe(false)
  role.vm.$emit('update:modelValue','finance');role.vm.$emit('change','finance');await flushPromises()
  expect(w.text()).not.toContain('要收权请先切换为其他固定角色')
  expect(w.findAllComponents(ElCheckboxGroup).every(g=>!g.props('disabled'))).toBe(true)
  expect(w.findAllComponents(ElSelect).slice(2).every(s=>!s.props('disabled'))).toBe(true)
  expect(w.findComponent(ElTag).props('closable')).toBe(true)
  w.findAllComponents(ElCheckboxGroup)[0].vm.$emit('update:modelValue',['finance:read']);await flushPromises()
  await w.findAll('button').find(b=>b.text()==='保存真实账号与授权')!.trigger('click');await flushPromises()
  expect(api.saveSystemUser).toHaveBeenCalledWith(10,expect.objectContaining({roleCode:'finance',permissions:['finance:read'],beforeVersion:7,password:'',scopes:[{entityType:'file',entityId:99}]}));expect(api.getSystemUsers).toHaveBeenCalledTimes(2)
  // Stored subset flags do not reduce an account's actual administrator grant.
  api.getSystemUsers.mockResolvedValue([{...financeUser,allPermissions:true,allObjects:false,permissions:[],fieldGroups:[]}])
  await w.findAll('button').find(b=>b.text()==='刷新')!.trigger('click');await flushPromises()
  expect(w.find('.el-table').text()).toContain('管理员')
  await w.findAll('button').find(b=>b.text()==='编辑 / 授权')!.trigger('click');await flushPromises()
  expect(w.findAllComponents(ElSelect)[0].props('modelValue')).toBe('administrator')
  expect(w.findAllComponents(ElCheckboxGroup)[0].props('modelValue')).toEqual(['*'])
  expect(w.findAllComponents(ElCheckbox)[0].props()).toMatchObject({modelValue:true,disabled:true})
 })
 it('does not fabricate users when the real API fails',async()=>{api.getSystemUsers.mockRejectedValue(new Error('not connected'));const w=mount(SystemUserManagementView,{global:{plugins:[ElementPlus]}});wrappers.push(w);await flushPromises();expect(w.text()).toContain('真实账号加载失败');expect(w.text()).not.toContain('财务负责人')})
})
