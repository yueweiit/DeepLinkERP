import { AxiosHeaders, type AxiosResponse } from 'axios'
import { createPinia, disposePinia, setActivePinia, type Pinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { unwrapResponse, type ApiResponse } from '@/api/request'
import { useUserStore } from '../user'
import { useCollaborationWorkspace } from '../collaborationWorkspace'
import { useFinanceWorkspace } from '../financeWorkspace'
import { editFinanceCell } from '@/views/development/financeDrafts'
import type { CollaborationRow } from '@/types/collaboration'
const auth = vi.hoisted(() => ({ loginByPassword:vi.fn(),loginByDingTalkCode:vi.fn(),getProfileByToken:vi.fn(),logout:vi.fn() }))
vi.mock('@/api/modules/auth', () => auth)
const session = (token:string) => ({ token,profile:{userId:1,userName:token,roleName:'测试',department:'测试'},permissions:['finance:write'] })
function expired(token:string):AxiosResponse<ApiResponse<null>> { return {data:{code:40101,message:'会话失效',data:null},status:200,statusText:'OK',headers:new AxiosHeaders(),config:{headers:new AxiosHeaders({Authorization:`Bearer ${token}`})}} }
let pinia:Pinia
beforeEach(() => { vi.clearAllMocks();localStorage.clear();pinia=createPinia();setActivePinia(pinia);auth.loginByPassword.mockResolvedValue(session('old'));auth.logout.mockResolvedValue(undefined) })
afterEach(() => { disposePinia(pinia);localStorage.clear();window.location.hash='' })
describe('one real Pinia session invalidation', () => {
  it('clears profile, permissions and both existing draft workspaces on a current-session 401',async()=>{
    const user=useUserStore();await user.login({username:'test',password:'test-only'})
    const collaboration=useCollaborationWorkspace(),finance=useFinanceWorkspace().forEntity('budget')
    collaboration.drafts.set({itemId:1,notes:null} as CollaborationRow,'notes','previous-session')
    editFinanceCell(finance.drafts,1,{budgetId:1,currencyCode:'CNY',moldCost:null},'moldCost','0')
    window.location.hash='/molds';expect(()=>unwrapResponse(expired('old'))).toThrow('会话失效')
    expect(user.token).toBe('');expect(user.profile).toBeNull();expect(user.permissions).toEqual([]);expect(user.isLoggedIn).toBe(false);expect(localStorage.getItem('plm_token')).toBeNull()
    expect(collaboration.drafts.rows.size).toBe(0);expect(finance.drafts.size).toBe(0);expect(window.location.hash).toBe('#/login?redirect=%2Fmolds')
    auth.loginByPassword.mockResolvedValue(session('again'));await user.login({username:'test',password:'test-only'})
    window.location.hash='/dashboard';expect(()=>unwrapResponse(expired('again'))).toThrow();expect(user.isLoggedIn).toBe(false);expect(window.location.hash).toContain('#/login?redirect=')
  })
  it('preserves a later login and its drafts when old 401, restore or logout responses arrive',async()=>{
    const user=useUserStore();await user.login({username:'test',password:'test-only'})
    let rejectRestore!:(error:Error)=>void
    auth.getProfileByToken.mockReturnValue(new Promise((_resolve,reject)=>{rejectRestore=reject}))
    const restoring=user.restore();auth.loginByPassword.mockResolvedValue(session('new'));await user.login({username:'test',password:'test-only'})
    const finance=useFinanceWorkspace().forEntity('budget');editFinanceCell(finance.drafts,1,{budgetId:1,currencyCode:'CNY',moldCost:null},'moldCost','0')
    window.location.hash='/dashboard';expect(()=>unwrapResponse(expired('old'))).toThrow();rejectRestore(new Error('old restore expired'));await expect(restoring).rejects.toThrow()
    expect(user.token).toBe('new');expect(user.profile?.userName).toBe('new');expect(user.permissions).toEqual(['finance:write']);expect(finance.drafts.size).toBe(1);expect(window.location.hash).toBe('#/dashboard')
    let rejectLogout!:(error:Error)=>void
    auth.logout.mockReturnValue(new Promise((_resolve,reject)=>{rejectLogout=reject}));const loggingOut=user.logout()
    auth.loginByPassword.mockResolvedValue(session('newest'));await user.login({username:'test',password:'test-only'})
    rejectLogout(new Error('old logout expired'));await expect(loggingOut).rejects.toThrow()
    expect(user.token).toBe('newest');expect(user.profile?.userName).toBe('newest');expect(localStorage.getItem('plm_token')).toBe('newest')
  })
})
