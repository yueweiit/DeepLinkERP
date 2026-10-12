import { beforeEach, describe, expect, it, vi } from 'vitest'
const http=vi.hoisted(()=>({get:vi.fn(),post:vi.fn()}))
vi.mock('@/api/request',()=>({default:http,unwrapResponse:(r:{data:{data:unknown}})=>r.data.data}))
import { loginByPassword, loginByDingTalkCode } from '../auth'
beforeEach(()=>vi.clearAllMocks())
describe('one auth session for desktop and DingTalk',()=>{
 it('uses server permissions rather than granting all logged-in accounts engineering access',async()=>{http.post.mockResolvedValue({data:{data:{token:'local-test',user:{userId:7,username:'supplier01',displayName:'供应商',roleCode:'supplier',departmentName:'制模厂',allPermissions:false,permissions:['pilot:tasks']}}}});const session=await loginByPassword({username:'supplier01',password:'not-a-real-password'});expect(session.permissions).toEqual(['pilot:tasks']);expect(session.profile.roleName).toBe('供应商');expect(session.profile.department).toBe('制模厂')})
 it('normalizes SSO through the existing token session shape',async()=>{http.post.mockResolvedValue({data:{data:{token:'sso-test',user:{userId:8,username:'mx01',displayName:'墨西哥',roleCode:'mexico',allPermissions:false,permissions:['pilot:tasks','task:arrival']}}}});const session=await loginByDingTalkCode('one-use-test-code');expect(http.post).toHaveBeenCalledWith('/pilot/dingtalk/login',{code:'one-use-test-code'});expect(session.permissions).toEqual(['pilot:tasks','task:arrival']);expect(session.token).toBe('sso-test')})
})
