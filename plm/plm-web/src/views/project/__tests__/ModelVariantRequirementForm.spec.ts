import ElementPlus from 'element-plus'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const orderApi = vi.hoisted(() => ({ getRequirementForm: vi.fn(), saveRequirementForm: vi.fn(), confirmRequirementForm: vi.fn() }))
vi.mock('@/api/modules/order', () => orderApi)
import ModelVariantRequirementForm from '../components/ModelVariantRequirementForm.vue'

describe('ModelVariantRequirementForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    orderApi.getRequirementForm.mockResolvedValue({ projectId: 9, dingTalkApprovalNo: 'DT-001', productName: '超队 3.0', model: 'iPhone 18', tipo: '精孔磁吸壳', status: 'draft', colors: [
    { variantColorId: 1, colorCode: '01', colorName: '黑色', selected: true }, { variantColorId: 2, colorCode: '02', colorName: '透明色', selected: true }
    ] })
  })
  it('shows one editable form with readonly approval and all colors selected', async () => {
    const wrapper = mount(ModelVariantRequirementForm, { props: { projectId: 9 }, global: { plugins: [ElementPlus] } }); await flushPromises()
    expect(wrapper.text()).toContain('新型号项目信息完善表'); expect(wrapper.text()).toContain('黑色'); expect(wrapper.text()).toContain('透明色')
    const approvalInput = wrapper.find('input[readonly]').element as HTMLInputElement
    expect(approvalInput.value).toBe('DT-001'); expect(approvalInput.readOnly).toBe(true)
    expect(wrapper.findAll('input[type="checkbox"]')).toHaveLength(2)
    expect(wrapper.findAll('input[type="checkbox"]').every(item => (item.element as HTMLInputElement).checked)).toBe(true)
  })

  it('confirms the form and emits the saved value so the host can load the timeline', async () => {
    const confirmed = {
      projectId: 9,
      dingTalkApprovalNo: 'DT-001',
      productName: '超队 3.0',
      model: 'iPhone 18',
      status: 'confirmed',
      colors: [{ variantColorId: 1, colorCode: '01', colorName: '黑色', selected: true }]
    }
    orderApi.confirmRequirementForm.mockResolvedValue(confirmed)
    const wrapper = mount(ModelVariantRequirementForm, { props: { projectId: 9 }, global: { plugins: [ElementPlus] } })
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text().includes('确认并进入下一步'))?.trigger('click')
    await flushPromises()

    expect(orderApi.confirmRequirementForm).toHaveBeenCalledWith(9, expect.objectContaining({
      selectedVariantColorIds: [1, 2]
    }))
    expect(wrapper.emitted('confirmed')?.[0]?.[0]).toEqual(confirmed)
    expect(wrapper.text()).toContain('项目时间轴已启动')
  })

  it('reloads when the host switches to another project', async () => {
    const wrapper = mount(ModelVariantRequirementForm, { props: { projectId: 9 }, global: { plugins: [ElementPlus] } })
    await flushPromises()

    await wrapper.setProps({ projectId: 10 })
    await flushPromises()

    expect(orderApi.getRequirementForm).toHaveBeenLastCalledWith(10)
  })
})
