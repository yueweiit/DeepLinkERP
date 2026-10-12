import { describe, expect, it } from 'vitest'
import type { CollaborationRow, PlanField, RowResult } from '@/types/collaboration'
import { brandFromModel, CollaborationDrafts, parseCell, parseClipboard, rowKey, suggestedArrivalDate, validateMoldRow } from '../collaboration'

const row = (id = 1): CollaborationRow => ({ itemId:id,productLineId:null,styleName:'薇武士',brand:'HONOR',compatibleModels:'Honor Test',phoneModelCode:'0001',phonePrice:null,priceCurrency:null,salesPlatform:null,referenceUrl:null,notes:null,pcTotal:null,tpuTotal:null,finishedTotal:null,productionNotes:null,projectCount:3,projects:[],moldSetCount:2,status:'linked',updatedAt:'2026-10-09' })
const field = (kind:string): PlanField => ({ key:'pcTotal',label:'累计数量',group:'production',kind,maxLength:0 })
const result = (id:number,status:RowResult['status']): RowResult => ({ entityType:'item',id,status,message:status,conflicts:[],row:null })

describe('collaboration cells and Excel clipboard', () => {
  it('keeps unknown distinct from zero and never reads quantities from remarks', () => {
    expect(parseCell(field('count'),'')).toBeNull();expect(parseCell(field('count'),'0')).toBe(0)
    expect(parseCell(field('count'),'5,400')).toBe(5400)
    for (const text of ['OK 5400','-1','1.5','9007199254740992']) expect(() => parseCell(field('count'),text)).toThrow()
    expect(parseCell(field('text'),'OK 5400')).toBe('OK 5400')
  })
  it('preserves leading zeros and validates real dates in supported formats', () => {
    expect(parseCell(field('code'),'0001')).toBe('0001');expect(() => parseCell(field('code'),'1')).toThrow()
    expect(parseCell(field('date'),'21/08/2026')).toBe('2026-08-21')
    expect(parseCell(field('date'),'2026/8/21')).toBe('2026-08-21')
    expect(parseCell(field('date'),'2026年8月21日')).toBe('2026-08-21')
    expect(() => parseCell(field('date'),'2026-02-30')).toThrow()
  })
  it('supports rectangular TSV including quoted multiline and trailing blank cells', () => {
    expect(parseClipboard('0\t12\t\r\n1\t2\t3\r\n')).toEqual([['0','12',''],['1','2','3']])
    expect(parseClipboard('"市场\n备注"\t"含""引号"\n')).toEqual([['市场\n备注','含"引号']])
    expect(() => parseClipboard('"未结束')).toThrow()
  })
  it('only offers a suggestion and crosses month/year boundaries correctly', () => {
    expect(suggestedArrivalDate(null)).toBeNull();expect(suggestedArrivalDate('2026-12-28')).toBe('2027-01-04')
  })
  it('recognises explicit Apple and Samsung prefixes, but does not guess ambiguous abbreviations',()=>{
    expect(brandFromModel('Apple iPhone 18 Pro Max')).toBe('Apple');expect(brandFromModel('Samsung Galaxy A37 5G')).toBe('Samsung')
    expect(brandFromModel('SM A04/A04S')).toBeNull();expect(brandFromModel('Appleton A5')).toBeNull()
  })
})
describe('colour-neutral drafts and optimistic saves', () => {
  it('normalises explicit locations and acceptance without treating unknown as arrived',()=>{
    expect(parseCell(field('location'),'未知')).toBeNull();expect(parseCell(field('location'),'墨西哥工厂')).toBe('mexico_factory');expect(parseCell(field('acceptance'),'验收通过')).toBe('passed');expect(()=>parseCell(field('acceptance'),'')).toThrow();expect(()=>parseCell(field('location'),'快递已签收')).toThrow()
  })
  it('does not use Mexico arrival to satisfy part acceptance, and requires dates and failure notes',()=>{
    const mold:CollaborationRow={...row(),moldSetId:3,actualMexicoArrivalDate:'2026-08-01',pcAcceptanceStatus:'passed'}
    expect(validateMoldRow(mold,key=>(mold[key] as string)??null)).toContain('实际到厂日期')
    const valid:CollaborationRow={...mold,pcFactoryArrivalDate:'2026-08-03',pcAcceptanceDate:'2026-08-03'};expect(validateMoldRow(valid,key=>(valid[key] as string)??null)).toBeNull()
    const failed:CollaborationRow={...valid,tpuAcceptanceStatus:'failed'};expect(validateMoldRow(failed,key=>(failed[key] as string)??null)).toContain('问题说明')
  })
  it('stores only changed fields and keeps the original value when refreshed rows arrive', () => {
    const drafts=new CollaborationDrafts();drafts.set(row(),'pcTotal',0)
    drafts.set({...row(),pcTotal:20},'pcTotal',30)
    expect(drafts.patches()[0].changes).toEqual([{field:'pcTotal',before:null,after:30,reason:undefined}])
    expect(drafts.value({...row(),pcTotal:20},'pcTotal')).toBe(30)
    drafts.set(row(),'pcTotal',null);expect(drafts.rows.size).toBe(0)
  })
  it('keeps failed/conflicting rows while successful rows clear independently', () => {
    const drafts=new CollaborationDrafts();drafts.set(row(1),'pcTotal',1);drafts.set(row(2),'pcTotal',2)
    drafts.apply(result(1,'saved'));drafts.apply(result(2,'forbidden'))
    expect(drafts.rows.size).toBe(1);expect(drafts.rows.get('item:2')?.result?.status).toBe('forbidden')
  })
  it('requires explicit conflict resolution and updates the baseline to current, including null', () => {
    const drafts=new CollaborationDrafts();drafts.set({...row(),pcTotal:100},'pcTotal',90)
    drafts.apply({...result(1,'conflict'),conflicts:[{field:'pcTotal',label:'PC',before:100,current:null,attempted:90}]})
    drafts.resolve('item:1','pcTotal',true);drafts.set(row(),'pcTotal',80)
    expect(drafts.patches()[0].changes[0].before).toBeNull()
    drafts.apply({...result(1,'conflict'),conflicts:[{field:'pcTotal',label:'PC',before:null,current:120,attempted:80}]})
    drafts.resolve('item:1','pcTotal',false);expect(drafts.rows.size).toBe(0)
  })
  it('preserves edits made during an in-flight save and rebases only the saved field', () => {
    const drafts=new CollaborationDrafts();drafts.set(row(),'pcTotal',100)
    const submitted=drafts.patches()[0];drafts.set(row(),'pcTotal',120);drafts.set(row(),'tpuTotal',90)
    drafts.apply({...result(1,'saved'),row:{...row(),pcTotal:100}},submitted)
    expect(drafts.patches()[0].changes).toEqual([{field:'pcTotal',before:100,after:120,reason:undefined},{field:'tpuTotal',before:null,after:90,reason:undefined}])
    const next={...drafts.patches()[0],changes:drafts.patches()[0].changes.filter(c=>c.field==='pcTotal')}
    drafts.set(row(),'pcTotal',0);drafts.apply({...result(1,'saved'),row:{...row(),pcTotal:null}},next)
    expect(drafts.patches()[0].changes).toEqual([{field:'pcTotal',before:null,after:0,reason:undefined},{field:'tpuTotal',before:null,after:90,reason:undefined}])
    const zero={...drafts.patches()[0],changes:drafts.patches()[0].changes.filter(c=>c.field==='pcTotal')}
    drafts.set(row(),'pcTotal',5);drafts.apply({...result(1,'saved'),row:{...row(),pcTotal:0}},zero)
    expect(drafts.patches()[0].changes[0]).toMatchObject({before:0,after:5})
  })
  it('distinguishes mold copies but never creates one production row per color or copy', () => {
    expect(rowKey(row())).toBe('item:1');expect(rowKey({...row(),moldSetId:3})).toBe('mold_set:3')
    const drafts=new CollaborationDrafts();drafts.set(row(),'pcTotal',0);drafts.set({...row(),projectCount:7,moldSetCount:3},'tpuTotal',25)
    expect(drafts.patches()).toHaveLength(1)
  })
  it('retains an explicit unchanged-date confirmation for the server basis audit', () => {
    const mold={...row(),moldSetId:3,plannedFactoryArrivalDate:'2026-08-21'}
    const drafts=new CollaborationDrafts();drafts.set(mold,'plannedFactoryArrivalDate','2026-08-21',true)
    expect(drafts.patches()[0].changes[0]).toMatchObject({before:'2026-08-21',after:'2026-08-21'})
    const submitted=drafts.patches()[0];drafts.set(mold,'plannedFactoryArrivalDate','2026-08-22',true)
    drafts.apply({entityType:'mold_set',id:3,status:'saved',message:'saved',conflicts:[],row:mold},submitted)
    expect(drafts.rows.get('mold_set:3')?.changes.get('plannedFactoryArrivalDate')).toMatchObject({before:'2026-08-21',after:'2026-08-22',confirm:true})
    drafts.clear();expect(drafts.patches()).toHaveLength(0)
  })
})
