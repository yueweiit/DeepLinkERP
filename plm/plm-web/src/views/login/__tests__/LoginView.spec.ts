import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import { afterEach, describe, expect, it, vi } from 'vitest'
vi.mock('@/stores/user',()=>({useUserStore:()=>({login:vi.fn(),loginDingTalk:vi.fn(),hasPermission:()=>false,profile:null})}))
vi.mock('@/api/modules/pilot',()=>({getPilotSsoStatus:vi.fn().mockResolvedValue({enabled:false,corpId:'',message:'未启用钉钉免登'})}))
let wrapper:VueWrapper|undefined
afterEach(()=>{wrapper?.unmount();vi.unstubAllEnvs()})
describe('production login credential boundary',()=>{
  it('starts empty and hides legacy test credentials when DEV is false',async()=>{
    vi.stubEnv('DEV',false)
    const LoginView=(await import('../LoginView.vue')).default
    const router=createRouter({history:createMemoryHistory(),routes:[{path:'/login',component:LoginView}]})
    await router.push('/login');await router.isReady()
    wrapper=mount(LoginView,{global:{plugins:[router,ElementPlus]}});await flushPromises()
    expect(wrapper.findAll('input').map(input=>(input.element as HTMLInputElement).value)).toEqual(['',''])
    expect(wrapper.text()).not.toContain('后端 M1 测试账号');expect(wrapper.text()).not.toContain('engineer01');expect(wrapper.text()).not.toContain('plm123456')
    expect(wrapper.text()).toContain('钉钉轻应用免登')
  })
})
