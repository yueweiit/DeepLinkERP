import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import ElementPlus, { ElCheckbox } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CollaborationOptions, ImportPreview, ImportRow } from '@/types/collaboration'

const api=vi.hoisted(()=>({previewCollaborationImport:vi.fn(),commitCollaborationImport:vi.fn(),getCollaborationPage:vi.fn(),getCollaborationItem:vi.fn(),downloadCollaborationTemplate:vi.fn()}))
vi.mock('@/api/modules/collaboration',()=>api)
import CollaborationImportDialog from '../components/CollaborationImportDialog.vue'

const options:CollaborationOptions={administrator:true,userId:1,productLines:[],writableGroups:['engineering','logistics'],itemFields:[],moldFields:[
  {key:'openedDate',label:'开模日期',group:'engineering',kind:'date',maxLength:0},
  {key:'plannedFactoryArrivalDate',label:'计划到墨西哥工厂',group:'logistics',kind:'date',maxLength:0}
]}
const source:ImportRow={rowNo:3,sheetName:'Sheet1',raw:{备注:'OK 5400'},values:{openedDate:'2026-06-15',plannedFactoryArrivalDate:'2026-07-20'},before:{openedDate:null,plannedFactoryArrivalDate:null},itemId:3,moldSetId:9,productLineId:1,styleName:'薇武士',brand:'Apple',compatibleModels:'Apple iPhone 18 Pro Max',newMoldSet:false,alreadyImported:false,issues:['计划到厂日期来自公式，请人工确认']}
const preview:ImportPreview={importToken:'local-preview',kind:'delivery',fileName:'delivery.xlsx',rows:[source,{...source,rowNo:4,alreadyImported:true}],total:2,needsReview:1}
let wrapper:VueWrapper|undefined
beforeEach(()=>{
  vi.clearAllMocks();api.previewCollaborationImport.mockResolvedValue(preview)
  api.getCollaborationPage.mockResolvedValue({content:[],page:1,size:50,totalElements:0,totalPages:0})
  api.commitCollaborationImport.mockResolvedValue({saved:1,skipped:1,duplicate:false})
})
afterEach(()=>{wrapper?.unmount();wrapper=undefined})
async function start() {
  wrapper=mount(CollaborationImportDialog,{props:{modelValue:true,kind:'delivery',options},global:{plugins:[ElementPlus]}})
  await flushPromises()
  const input=wrapper.get('input[type="file"]')
  Object.defineProperty(input.element,'files',{value:[new File(['test'],'delivery.xlsx')]})
  await input.trigger('change');await wrapper.findAll('button').find(b=>b.text()==='读取预览')!.trigger('click');await flushPromises()
  return wrapper
}
async function include() {wrapper!.findAllComponents(ElCheckbox).find(c=>c.text()==='确认本行纳入导入')!.vm.$emit('change',true);await flushPromises()}
async function submit() {await wrapper!.findAll('button').find(b=>b.text().startsWith('确认导入'))!.trigger('click');await flushPromises()}

describe('collaboration import review',()=>{
  it('previews only, defaults ambiguous rows to skipped and keeps original notes untouched',async()=>{
    const w=await start();expect(w.text()).toContain('已选择导入 0 行');expect(w.text()).toContain('原始文件和历史项目尚未改动')
    expect(w.text()).toContain('OK 5400');expect(api.commitCollaborationImport).not.toHaveBeenCalled()
    expect(w.findAllComponents(ElCheckbox)[1].props('disabled')).toBe(true)
  })
  it('requires review reasons and submits corrected dates with original values and stable IDs',async()=>{
    const w=await start();const date=w.get('input[aria-label="计划到墨西哥工厂"]')
    ;(date.element as HTMLInputElement).value='2026-07-23';await date.trigger('input')
    await include();await submit();expect(api.commitCollaborationImport).not.toHaveBeenCalled()
    await w.get('textarea[placeholder="说明别名映射、品牌或日期修正；数量下调也在此说明"]').setValue('负责人已确认到厂计划')
    await submit();expect(api.commitCollaborationImport).toHaveBeenCalledWith('local-preview',expect.arrayContaining([expect.objectContaining({itemId:3,moldSetId:9,skip:false,reviewReason:'负责人已确认到厂计划',values:{openedDate:'2026-06-15',plannedFactoryArrivalDate:'2026-07-23'},before:{openedDate:null,plannedFactoryArrivalDate:null}})]))
    expect(w.emitted('imported')).toHaveLength(1);expect(w.emitted('update:modelValue')?.[0]).toEqual([false])
  })
  it('retains the preview and corrected fields after a server conflict',async()=>{
    const w=await start();await include();await w.get('textarea[placeholder="说明别名映射、品牌或日期修正；数量下调也在此说明"]').setValue('人工核对')
    api.commitCollaborationImport.mockRejectedValue(new Error('同一字段已被其他人修改'))
    await submit();expect(w.text()).toContain('同一字段已被其他人修改');expect(w.text()).toContain('已选择导入 1 行')
    expect(w.emitted('imported')).toBeUndefined();expect(w.emitted('update:modelValue')).toBeUndefined()
  })
})
