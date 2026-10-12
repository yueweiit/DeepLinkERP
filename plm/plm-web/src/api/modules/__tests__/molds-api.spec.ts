import { beforeEach, describe, expect, it, vi } from 'vitest'
const request=vi.hoisted(()=>({get:vi.fn(),post:vi.fn()}))
vi.mock('../../request',()=>({default:request,unwrapResponse:(r:{data:{data:unknown}})=>r.data.data,unwrapPage:(r:{data:{data:unknown}})=>r.data.data}))
import { getMolds,getMold,getMoldHistory,getMoldReferences,createMold,copyMold,saveMolds,getMoldInventoryOptions } from '../molds'
describe('mold API shared physical records',()=>{
  beforeEach(()=>{vi.clearAllMocks();request.get.mockResolvedValue({data:{data:{content:[]}}});request.post.mockResolvedValue({data:{data:{moldSetId:1}}})})
  it('uses server paging, per-part location filtering and the detail endpoint',async()=>{const q={view:'delivery' as const,page:2,size:50,location:'unknown',status:'partially_arrived'};await getMolds(q);expect(request.get).toHaveBeenCalledWith('/molds',{params:q});await getMold(1);await getMoldReferences(1);await getMoldHistory(1,2);expect(request.get).toHaveBeenCalledWith('/molds/1');expect(request.get).toHaveBeenCalledWith('/molds/1/references');expect(request.get).toHaveBeenCalledWith('/molds/1/history',{params:{page:2,size:20}})})
  it('creates or copies sets without changing historical codes, actor or production totals',async()=>{await createMold(1,'首套');await copyMold(2,'复制套');expect(request.post).toHaveBeenCalledWith('/molds',{itemId:1,setName:'首套'});expect(request.post).toHaveBeenCalledWith('/molds/2/copies',{setName:'复制套'})})
  it('saves original-value field patches and searches inventory references read-only',async()=>{const rows=[{entityType:'mold_set' as const,id:1,changes:[{field:'pcAcceptanceStatus',before:'pending',after:'passed'}]}];await saveMolds(rows);await getMoldInventoryOptions('000001');expect(request.post).toHaveBeenCalledWith('/molds/batch-save',{rows});expect(request.get).toHaveBeenCalledWith('/molds/inventory-options',{params:{keyword:'000001'}})})
})
