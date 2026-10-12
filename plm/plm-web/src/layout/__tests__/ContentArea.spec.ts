import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it } from 'vitest'
import { useUserStore } from '@/stores/user'
import ContentArea from '../ContentArea.vue'

const cachedPages = [
  ['/inventories', 'InventoryCenterView'], ['/bom', 'BomCenterView'],
  ['/collaboration-plans', 'CollaborationPlanView'], ['/molds', 'MoldManagementView'],
  ['/mold-schedules', 'MoldScheduleView'], ['/development-budgets', 'DevelopmentBudgetView'],
  ['/development-expenses', 'DevelopmentExpenseView']
] as const
let wrapper: VueWrapper | undefined
afterEach(() => { wrapper?.unmount(); localStorage.clear() })

async function start() {
  const pinia = createPinia(); setActivePinia(pinia)
  const user = useUserStore(); user.token = 'cache-test-account'
  const starts = new Map<string, number>()
  const routes = [...cachedPages, ['/dashboard', 'Dashboard'], ['/market-watch', 'MarketWatch']].map(([path, name]) => ({
    path, component: defineComponent({ name, setup() {
      starts.set(name!, (starts.get(name!) || 0) + 1)
      const draft = ref('')
      return () => h('input', { value: draft.value, onInput: (event: Event) => { draft.value = (event.target as HTMLInputElement).value } })
    } })
  }))
  const router = createRouter({ history: createMemoryHistory(), routes })
  await router.push('/inventories'); await router.isReady()
  wrapper = mount(ContentArea, { global: { plugins: [pinia, router] } }); await flushPromises()
  return { wrapper, router, user, starts }
}

describe('business-page keep-alive and full-width layout', () => {
  it('retains all seven real named business editors without evicting the first draft', async () => {
    const { wrapper, router, starts } = await start()
    for (const [path] of cachedPages) { await router.push(path); await flushPromises(); await wrapper.get('input').setValue(`draft:${path}`) }
    await router.push('/dashboard'); await flushPromises()
    for (const [path, name] of cachedPages) {
      await router.push(path); await flushPromises()
      expect((wrapper.get('input').element as HTMLInputElement).value).toBe(`draft:${path}`)
      expect(starts.get(name)).toBe(1)
    }
  })
  it('uses the shared edge-to-edge canvas for schedule, budget and expense alongside existing collaboration pages', async () => {
    const { wrapper, router } = await start()
    for (const path of ['/collaboration-plans', '/molds', '/market-watch', '/mold-schedules', '/development-budgets', '/development-expenses']) {
      await router.push(path); await flushPromises(); expect(wrapper.get('main').classes()).toContain('content-area--collaboration')
    }
    await router.push('/dashboard'); await flushPromises(); expect(wrapper.get('main').classes()).not.toContain('content-area--collaboration')
  })
  it('discards cached drafts when the real session token changes', async () => {
    const { wrapper, router, user, starts } = await start()
    await wrapper.get('input').setValue('previous-account-draft')
    await router.push('/development-budgets'); await flushPromises(); await wrapper.get('input').setValue('previous-budget')
    user.token = 'next-real-account'; await flushPromises()
    expect((wrapper.get('input').element as HTMLInputElement).value).toBe('')
    await router.push('/inventories'); await flushPromises()
    expect((wrapper.get('input').element as HTMLInputElement).value).toBe('')
    expect(starts.get('InventoryCenterView')).toBe(2)
  })
})
