import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus, { ElPagination } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ getCodeItems: vi.fn(), getPhoneModelReview: vi.fn(), createCodeItem: vi.fn(),
  updateCodeItem: vi.fn(), disableCodeItem: vi.fn(), enableCodeItem: vi.fn() }))
vi.mock('@/api/modules/code', () => api)
import PhoneModelCodeView from '../PhoneModelCodeView.vue'
import CodeItemDialog from '../components/CodeItemDialog.vue'

beforeEach(() => {
  vi.clearAllMocks()
  api.getCodeItems.mockResolvedValue({ content: [{ codeItemId: 101, codeType: 'phone_model', codeValue: '0001',
    codeName: 'Apple iPhone 16', status: 'enabled', sortOrder: 0 }], page: 1, size: 50, totalElements: 1, totalPages: 1 })
  api.getPhoneModelReview.mockResolvedValue({ content: [{ key: '0064', codeValues: ['0064'], modelNames: ['iPhone 6', 'iPhone 7'], sourceCount: 2 }],
    page: 1, size: 50, totalElements: 1, totalPages: 1 })
  api.disableCodeItem.mockResolvedValue({})
  api.createCodeItem.mockResolvedValue({})
})

describe('PhoneModelCodeView', () => {
  it('does not reset to page one while a later server page is loading', async () => {
    api.getCodeItems.mockResolvedValue({ content: [{ codeItemId: 101, codeType: 'phone_model', codeValue: '0001',
      codeName: 'Apple iPhone 16', status: 'enabled', sortOrder: 0 }], page: 1, size: 50, totalElements: 305, totalPages: 7 })
    const wrapper = mount(PhoneModelCodeView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    wrapper.getComponent(ElPagination).vm.$emit('current-change', 7)
    await flushPromises()
    expect(api.getCodeItems).toHaveBeenLastCalledWith(expect.objectContaining({ page: 7, codeType: 'phone_model' }))
    expect(wrapper.getComponent(ElPagination).props('currentPage')).toBe(7)
    wrapper.unmount()
  })
  it('isolates phone codes, preserves leading zeros and loads the readonly review on demand', async () => {
    const wrapper = mount(PhoneModelCodeView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    expect(api.getCodeItems).toHaveBeenCalledWith(expect.objectContaining({ codeType: 'phone_model', size: 50 }))
    expect(wrapper.text()).toContain('0001')
    expect(api.getPhoneModelReview).not.toHaveBeenCalled()
    await wrapper.get('[data-test="phone-review-toggle"]').trigger('click')
    await flushPromises()
    expect(api.getPhoneModelReview).toHaveBeenCalledWith({ kind: 'code_many_names', page: 1, size: 50 })
    expect(wrapper.text()).toContain('iPhone 7')
    await wrapper.get('[data-test="toggle-phone-101"]').trigger('click')
    await flushPromises()
    expect(api.disableCodeItem).toHaveBeenCalledWith(101)
    wrapper.unmount()
  })

  it('uses a separate phone editor and supports name edits', async () => {
    const wrapper = mount(PhoneModelCodeView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    await wrapper.get('[data-test="edit-phone-code"]').trigger('click')
    const editor = wrapper.getComponent(CodeItemDialog)
    expect(editor.props('codeType')).toBe('phone_model')
    expect(editor.props('item')?.codeValue).toBe('0001')
    editor.vm.$emit('save', { codeType: 'phone_model', codeValue: '0001', codeName: 'Apple iPhone 16 Plus', sortOrder: 0 })
    await flushPromises()
    expect(api.updateCodeItem).toHaveBeenCalledWith(101, expect.objectContaining({ codeValue: '0001', codeName: 'Apple iPhone 16 Plus' }))
    wrapper.unmount()
  })
})

describe('Phone model editor', () => {
  it('requires four digits and disables the existing code field', async () => {
    const wrapper = mount(CodeItemDialog, { props: { modelValue: true, codeType: 'phone_model' },
      global: { plugins: [ElementPlus] }, attachTo: document.body })
    await flushPromises()
    const inputs = document.body.querySelectorAll<HTMLInputElement>('.el-dialog input')
    expect(inputs[1].getAttribute('maxlength')).toBe('4')
    const codeInput = wrapper.getComponent({ name: 'ElDialog' }).findAll('input')[1]
    const nameInput = wrapper.getComponent({ name: 'ElDialog' }).findAll('input')[2]
    await codeInput.setValue('001'); await nameInput.setValue('Model')
    expect(document.body.querySelector<HTMLButtonElement>('[data-test="save-code-item"]')?.disabled).toBe(true)
    await codeInput.setValue('0001')
    expect(document.body.querySelector<HTMLButtonElement>('[data-test="save-code-item"]')?.disabled).toBe(false)
    await wrapper.setProps({ item: { codeItemId: 101, codeType: 'phone_model', codeValue: '0001', codeName: 'Model', status: 'disabled', sortOrder: 0 } })
    expect(inputs[1].disabled).toBe(true)
    wrapper.unmount()
  })
})
