import ElementPlus, { ElDrawer, ElMessageBox, ElSelect } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const attachmentApi = vi.hoisted(() => ({
  getFileCenterAttachments: vi.fn(),
  downloadAttachment: vi.fn(),
  deleteAttachment: vi.fn(),
  getAttachmentVersions:vi.fn(),getAttachmentDetail:vi.fn(),getProductAttachments:vi.fn(),uploadAttachmentVersion:vi.fn(),publishAttachmentVersion:vi.fn()
}))
const foundationApi = vi.hoisted(() => ({ getFileSections: vi.fn() }))
const collaborationApi = vi.hoisted(() => ({getCollaborationPage:vi.fn()}))
const moldApi = vi.hoisted(() => ({getMolds:vi.fn()}))

vi.mock('@/api/modules/attachment', () => attachmentApi)
vi.mock('@/api/modules/foundation', () => foundationApi)
vi.mock('@/api/modules/collaboration',()=>collaborationApi)
vi.mock('@/api/modules/molds',()=>moldApi)
vi.mock('@/components/FixedTableViewport/index.vue',()=>({default:{template:'<div><slot :table-height="420" /></div>'}}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))

import FileCenterView from '../FileCenterView.vue'
import { useUserStore } from '@/stores/user'
import type { AttachmentVO } from '@/api/modules/attachment'
const file=(id=91, patch:Partial<AttachmentVO>={}):AttachmentVO=>({attachmentId:id,ownerObjectType:'Product',ownerObjectId:7,projectId:7,projectName:'平台工程',projectCode:'PLT-7',fileCategory:'engineering',fileName:'mold.step',originalFileName:'mold.step',fileExt:'step',previewType:'cad',fileSize:1024,checksum:'abc',storageType:'local',storageKey:`projects/7/${id}.step`,versionNo:'V1',status:'draft',createdBy:'real-engineer',createdAt:'2026-10-12T10:00:00',...patch})
async function versionsPage(permissions=['*']) {useUserStore().permissions=permissions;attachmentApi.getFileCenterAttachments.mockResolvedValue({content:[file()],page:1,size:20,totalElements:1,totalPages:1});const w=mount(FileCenterView,{global:{plugins:[ElementPlus]}});await flushPromises();await w.findAll('button').find(b=>b.text()==='版本 / 发布')!.trigger('click');await flushPromises();return w}

describe('FileCenterView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia());useUserStore().permissions=['*'];useUserStore().token='file-test'
    attachmentApi.getAttachmentVersions.mockResolvedValue([file()]);attachmentApi.getProductAttachments.mockResolvedValue([file(93,{fileExt:'pdf',previewType:'pdf',originalFileName:'mold.pdf'})]);collaborationApi.getCollaborationPage.mockResolvedValue({content:[{itemId:8,productLineId:7,styleName:'平台款式',compatibleModels:'Apple iPhone 18',projects:[]}],totalElements:1});moldApi.getMolds.mockResolvedValue({content:[{itemId:8,moldSetId:5,assetNumber:'MS-000005',setName:'首套'}]});attachmentApi.publishAttachmentVersion.mockResolvedValue(file(91,{status:'released',releasedAt:'2026-10-12T11:00:00'}))
    foundationApi.getFileSections.mockResolvedValue([])
    attachmentApi.getFileCenterAttachments.mockResolvedValue({
      content: [],
      page: 1,
      size: 20,
      totalElements: 0,
      totalPages: 0
    })
  })

  it('loads the real file-center page and shows a successful empty state', async () => {
    const wrapper = mount(FileCenterView, { global: { plugins: [ElementPlus] } })

    await flushPromises()

    expect(attachmentApi.getFileCenterAttachments).toHaveBeenCalledWith({ page: 1, size: 20 })
    expect(foundationApi.getFileSections).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('当前筛选条件下没有文件')
    expect(attachmentApi.getAttachmentVersions).not.toHaveBeenCalled()
  })

  it('renders attachment metadata returned by the backend', async () => {
    attachmentApi.getFileCenterAttachments.mockResolvedValue({
      content: [{
        attachmentId: 91,
        ownerObjectType: 'Product',
        ownerObjectId: 7,
        projectId: 7,
        projectCode: 'PRD-CD30-IP18-BLK-A',
        projectName: '超队 3.0 iPhone18 黑色',
        timelineNodeKey: 'sampling-process',
        fileCategory: 'testing',
        fileName: 'M4测试报告.txt',
        originalFileName: 'M4测试报告.txt',
        fileExt: 'txt',
        contentType: 'text/plain',
        fileSize: 1024,
        checksum: 'abc',
        storageType: 'local',
        storageKey: 'projects/7/report.txt',
        versionNo: 'V1',
        status: 'draft',
        remark: '联调',
        createdAt: '2026-07-14T12:00:00',
        createdBy: 'engineer01'
      }],
      page: 1,
      size: 20,
      totalElements: 1,
      totalPages: 1
    })

    const wrapper = mount(FileCenterView, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(wrapper.text()).toContain('M4测试报告.txt')
    expect(wrapper.text()).toContain('PRD-CD30-IP18-BLK-A')
    expect(wrapper.text()).toContain('超队 3.0 iPhone18 黑色')
    expect(wrapper.text()).toContain('sampling-process')
    expect(wrapper.text()).toContain('1 KB')
  })
  it('opens a wide family drawer with formal history and requires explicit scope selection',async()=>{
    attachmentApi.getAttachmentVersions.mockResolvedValue([file(),file(90,{versionNo:'V0',status:'released',releasedAt:'2026-10-11T10:00:00',changeReason:'首版发布'})]);const w=await versionsPage();expect(w.findComponent(ElDrawer).props('size')).toBe('96%');expect(w.text()).toContain('最近正式发布：V0');expect(w.text()).toContain('首版发布');expect(moldApi.getMolds).not.toHaveBeenCalled();expect(attachmentApi.publishAttachmentVersion).not.toHaveBeenCalled();w.unmount()
  })
  it('uploads a new draft version using the existing family and a mandatory change reason',async()=>{
    const w=await versionsPage();const input=w.get('input[aria-label="选择新版本文件"]'),upload=new File(['new'],'mold-V2.step');Object.defineProperty(input.element,'files',{value:[upload],configurable:true});await input.trigger('change');await w.get('input[placeholder="人工填写，例如 V2"]').setValue('V2');await w.get('textarea[placeholder="明确说明本次变更"]').setValue('增加加强筋');attachmentApi.uploadAttachmentVersion.mockResolvedValue(file(92,{versionNo:'V2',familyId:91}));attachmentApi.getAttachmentVersions.mockResolvedValue([file(92,{versionNo:'V2',familyId:91}),file()]);await w.get('[data-test="upload-file-version"]').trigger('click');await flushPromises();expect(attachmentApi.uploadAttachmentVersion).toHaveBeenCalledWith(91,upload,'V2','增加加强筋');expect(attachmentApi.publishAttachmentVersion).not.toHaveBeenCalled();w.unmount()
  })
  it('CAD publication is separate, requires an explicit PDF, and submits chosen IDs without guessing',async()=>{
    const w=await versionsPage();await w.get('textarea[placeholder="确认本版本及适用范围"]').setValue('工程确认版本及关联');await w.get('[data-test="release-file-version"]').trigger('click');await flushPromises();expect(attachmentApi.publishAttachmentVersion).not.toHaveBeenCalled();const select=(placeholder:string)=>w.findAllComponents(ElSelect).find(s=>s.props('placeholder')===placeholder)!;const selectors=[null,select('人工选择同项目关联档案'),select('人工选择，不按编码推断套数'),select('人工关联，不自动转换 CAD')];selectors[1]!.vm.$emit('update:modelValue',8);selectors[1]!.vm.$emit('change',8);await flushPromises();selectors[2]!.vm.$emit('update:modelValue',5);selectors[3]!.vm.$emit('update:modelValue',93);await flushPromises();expect(selectors[1]!.props('modelValue')).toBe(8);expect(selectors[2]!.props('modelValue')).toBe(5);expect(selectors[3]!.props('modelValue')).toBe(93);vi.spyOn(ElMessageBox,'confirm').mockResolvedValue('confirm' as never);await w.get('[data-test="release-file-version"]').trigger('click');await flushPromises();expect(attachmentApi.publishAttachmentVersion).toHaveBeenCalledWith(91,{reason:'工程确认版本及关联',itemId:8,moldSetId:5,pdfAttachmentId:93});w.unmount();vi.restoreAllMocks()
  })
  it('read-only accounts see only versions and never load publication controls or mutate files',async()=>{
    const w=await versionsPage(['file:read']);expect(w.find('[data-test="upload-file-version"]').exists()).toBe(false);expect(w.find('[data-test="release-file-version"]').exists()).toBe(false);expect(collaborationApi.getCollaborationPage).not.toHaveBeenCalled();expect(attachmentApi.getProductAttachments).not.toHaveBeenCalled();expect(w.findAll('button').some(b=>b.attributes('title')==='删除')).toBe(false);w.unmount()
  })
})
