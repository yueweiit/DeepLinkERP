import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  getCodeItems: vi.fn(), createCodeItem: vi.fn(), updateCodeItem: vi.fn(),
  enableCodeItem: vi.fn(), disableCodeItem: vi.fn(), previewCodeImport: vi.fn(), commitCodeImport: vi.fn()
}))
vi.mock('@/api/modules/code', () => api)

import CodeCenterView from '../CodeCenterView.vue'

describe('CodeCenterView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getCodeItems.mockResolvedValue({
      content: [{ codeItemId: 2, codeType: 'color', codeValue: '02', codeName: 'Negro', status: 'enabled', sortOrder: 2 }],
      page: 1, size: 20, totalElements: 1, totalPages: 1
    })
    api.disableCodeItem.mockResolvedValue({})
  })

  it('loads color codes and supports disable', async () => {
    const wrapper = mount(CodeCenterView, { global: { plugins: [ElementPlus] } })
    await vi.waitFor(() => expect(wrapper.text()).toContain('Negro'))
    expect(api.getCodeItems).toHaveBeenCalledWith(expect.objectContaining({ codeType: 'color', size: 200 }))
    expect(wrapper.text()).toContain('02')
    await wrapper.get('[data-test="disable-code-2"]').trigger('click')
    await vi.waitFor(() => expect(api.disableCodeItem).toHaveBeenCalledWith(2))
  })

  it('provides create and xlsx import actions', async () => {
    const wrapper = mount(CodeCenterView, { global: { plugins: [ElementPlus] } })
    await vi.waitFor(() => expect(api.getCodeItems).toHaveBeenCalled())
    expect(wrapper.find('[data-test="create-code-item"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="import-code-items"]').exists()).toBe(true)
  })
})
