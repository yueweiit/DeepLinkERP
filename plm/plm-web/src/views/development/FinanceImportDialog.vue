<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { commitBudgetFile, commitErpExpenses, previewBudgetFile, previewErpExpenses, refreshErpExpenses, type BudgetImportRow, type ErpImportRow, type FinanceEntity, type FinanceOptions, type FinancePreview, type FinanceRow } from '@/api/modules/development'
import { previewFormula, previewBreakEvenQuantity } from './financeDrafts'
const props = defineProps<{ entity: FinanceEntity; options: FinanceOptions; modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; completed: [] }>()
const user = useUserStore()
let generation = 0
const current = (ticket:number,token:string) => ticket===generation && token===user.token
const preview = ref<FinancePreview<BudgetImportRow | ErpImportRow>>()
const busy = ref(false), jsonText = ref('')
const columns = computed(() => props.entity === 'budget' ? ['moldCost','moldWeight','transportRate','fuelRate','customsCost','salePrice','unitProductionCost','budgetAmount'] : [])
const labels:Record<string,string>={moldCost:'模具费用',moldWeight:'重量 KG',transportRate:'运输费率 / KG',fuelRate:'燃油费率 / KG',customsCost:'清关费用',salePrice:'产品售价',unitProductionCost:'单件生产成本',budgetAmount:'手工预算'}
function open() { generation++;preview.value = undefined; jsonText.value = '';busy.value=false }
const close = () => { open();emit('update:modelValue', false) }
watch(() => user.token, close, {flush:'sync'})
watch(() => props.modelValue, visible => {if(!visible)open()})
onBeforeUnmount(() => {generation++})
async function choose(event: Event) { const input=event.target as HTMLInputElement; const file = input.files?.[0]; if (!file || !user.token) return; const ticket=++generation,token=user.token;preview.value=undefined;busy.value = true; try { const result=await previewBudgetFile(file);if(current(ticket,token))preview.value=result } catch { /* shared request message */ } finally { if(current(ticket,token))busy.value = false; input.value = '' } }
async function readErp() { if(!user.token)return;const ticket=++generation,token=user.token;preview.value=undefined;busy.value = true; try { const input = JSON.parse(jsonText.value); if (!Array.isArray(input)) throw new Error('请输入ERP已过账明细数组');const result=await previewErpExpenses(input);if(current(ticket,token))preview.value = result } catch (e) { if(current(ticket,token))ElMessage.error(e instanceof Error ? e.message : '预览失败') } finally { if(current(ticket,token))busy.value = false } }
async function pullErp(){if(!user.token)return;const ticket=++generation,token=user.token;preview.value=undefined;busy.value=true;try{const result=await refreshErpExpenses();if(!current(ticket,token))return;if(result.status==='not_configured')ElMessage.info(result.message);else preview.value=result}finally{if(current(ticket,token))busy.value=false}}
function asBudget(row: BudgetImportRow | ErpImportRow) { return row as BudgetImportRow }
function asErp(row: BudgetImportRow | ErpImportRow) { return row as ErpImportRow }
function selectItem(row: BudgetImportRow | ErpImportRow) { const item = props.options.items.find(i => i.itemId === row.itemId); row.productLineId = item?.productLineId ?? null; row.moldSetId = null; if(props.entity==='budget'&&item)asBudget(row).kind='mold' }
function changeKind(row:BudgetImportRow){if(row.kind==='platform'){row.itemId=null;row.moldSetId=null;row.parentBudgetId=null}}
function calculationRow(row:BudgetImportRow):FinanceRow{return {...row.values,currencyCode:row.currency,calculationMode:row.values.calculationMode||'mold_formula'}}
function selectBudget(row: BudgetImportRow) { const b = props.options.budgets.find(b => b.budgetId === row.budgetId); if (!b) { row.before = {}; return }; if(b.budgetKind)row.kind=b.budgetKind; row.productLineId = Number(b.productLineId) || null; row.itemId = Number(b.itemId) || null; row.moldSetId = Number(b.moldSetId) || null; row.parentBudgetId=Number(b.parentBudgetId)||null; row.before = Object.fromEntries(Object.keys(row.values).map(key => [key,b[key] ?? null])) }
async function commit() { if (!preview.value) return; const rows = preview.value.rows; if (rows.some(r => !r.skip && !(props.entity === 'budget' ? asBudget(r).reason?.trim() : asErp(r).mappingReason?.trim()))) { ElMessage.warning('请逐行填写核对说明，或勾选跳过'); return }
  const ticket=++generation,token=user.token;busy.value = true; try { const result = props.entity === 'budget' ? await commitBudgetFile(preview.value.token, rows as BudgetImportRow[]) : await commitErpExpenses(preview.value.token, rows as ErpImportRow[]);if(!current(ticket,token))return;ElMessage.success(`保存 ${result.saved} 行，跳过 ${result.skipped} 行`); emit('completed'); close() } catch { /* retain preview for correction */ } finally { if(current(ticket,token))busy.value = false } }
</script>
<template>
  <el-dialog :model-value="modelValue" :title="entity === 'budget' ? '预算 Excel 预览与映射确认' : 'ERP 已过账明细核对（离线）'" width="96%" top="3vh" destroy-on-close @open="open" @close="close">
    <el-alert :closable="false" type="warning" title="预览不会写入；没有外部接入凭据时不调用ERP。必须按档案/单据明细ID确认，不能按金额或颜色猜测。" />
    <div v-if="!preview" class="import-source">
      <template v-if="entity === 'budget'"><p>支持原模具成本预算表与携带稳定 ID 的新模板。运输 74.68、燃油 33.18 CNY/KG；空值与零分别保留。</p><input type="file" accept=".xlsx" :disabled="busy" @change="choose" /></template>
      <template v-else><el-button type="primary" :loading="busy" @click="pullErp">从服务器只读拉取ERP明细</el-button><p>服务器运行配置 PLM_PILOT_ERP_EXPENSES_URL/TOKEN；未配置明确提示，不伪造实时数据。仅GET只读拉取，HTTPS、不跟重定向，取得后仍须逐行核对，不自动提交。</p><p>也可核对离线导出：须含 voucherId、lineId、currency、postedAmount（冲销为负数）、description、docstatus=1。</p><el-input v-model="jsonText" type="textarea" :rows="8" placeholder="粘贴ERP导出的已过账JSON明细数组；不填测试数据到正式台账" /><el-button :loading="busy" @click="readErp">只读预览</el-button></template>
    </div>
    <template v-else>
      <p>{{ preview.note }} · {{ preview.total }} 行</p>
      <el-table :data="preview.rows" height="62vh" border row-key="rowNo">
        <el-table-column label="跳过" width="64" fixed><template #default="{ row }"><el-checkbox v-model="row.skip" /></template></el-table-column>
        <el-table-column label="原行 / 名称" min-width="200" fixed><template #default="{ row }"><strong>{{ row.sheetName || row.voucherId }} · {{ row.rowNo }}</strong><p>{{ row.name || row.description }}</p><small v-if="entity === 'expense'">{{ row.lineId }} · {{ row.currency }} {{ row.postedAmount }}<br />冲销关联：{{ row.reversalOf || '无' }}</small></template></el-table-column>
        <el-table-column v-if="entity==='budget'" label="预算层级" width="145"><template #default="{row}"><el-select v-model="asBudget(row).kind" :disabled="!!row.budgetId" @change="changeKind(asBudget(row))"><el-option label="平台测算" value="platform"/><el-option label="档案/模具" value="mold"/></el-select></template></el-table-column>
        <el-table-column label="产品平台" width="200"><template #default="{ row }"><el-select v-model="row.productLineId" filterable clearable placeholder="明确选择产品平台"><el-option v-for="p in options.productLines" :key="p.productId" :value="p.productId" :label="p.productName" /></el-select></template></el-table-column>
        <el-table-column label="协作档案（模具预算/费用）" width="275"><template #default="{ row }"><el-select v-model="row.itemId" filterable clearable placeholder="款式＋兼容型号，不按颜色" @change="selectItem(row)"><el-option v-for="i in options.items" :key="i.itemId" :value="i.itemId" :label="`${i.styleName} · ${i.compatibleModels}`" /></el-select></template></el-table-column>
        <el-table-column label="明确模具套（可选）" width="200"><template #default="{ row }"><el-select v-model="row.moldSetId" filterable clearable placeholder="可先按档案预算"><el-option v-for="s in options.molds.filter(s => s.itemId === row.itemId)" :key="s.moldSetId" :value="s.moldSetId" :label="`${s.setNo} · ${s.setName}`" /></el-select></template></el-table-column>
        <el-table-column v-if="entity === 'budget'" label="采用已有预算（可选）" width="230"><template #default="{ row }"><el-select v-model="row.budgetId" filterable clearable placeholder="更新须有稳定ID及原值" @change="selectBudget(asBudget(row))"><el-option v-for="b in options.budgets.filter(b=>b.currencyCode===row.currency)" :key="b.budgetId" :value="b.budgetId" :label="`${b.budgetName} · ${b.currencyCode}`" /></el-select></template></el-table-column>
        <el-table-column v-for="key in columns" :key="key" :label="labels[key]" width="145"><template #default="{ row }"><el-input v-model="asBudget(row).values[key]" :data-field="key" placeholder="未知留空" inputmode="decimal" /></template></el-table-column>
        <el-table-column v-if="entity === 'budget'" label="修正后测算 / 最小回本量" width="190"><template #default="{ row }"><div>{{ row.currency }} {{ previewFormula(calculationRow(asBudget(row))) ?? '未知' }}</div><div>{{ previewBreakEvenQuantity(calculationRow(asBudget(row))) ?? '无法测算' }} 件</div><small>保存以服务器复算为准</small></template></el-table-column>
        <el-table-column label="原始公式 / 核对问题" width="230"><template #default="{ row }"><el-popover trigger="click" :width="500"><p v-for="issue in row.issues" :key="issue">{{ issue }}</p><pre v-if="entity === 'budget'">{{ asBudget(row).formulas }}</pre><template #reference><el-button link :type="row.issues.length?'warning':'primary'">查看原表 · {{ row.issues.length }} 项核对</el-button></template></el-popover></template></el-table-column>
        <el-table-column label="映射 / 修订说明（必填）" width="300"><template #default="{ row }"><el-input v-if="entity === 'budget'" v-model="asBudget(row).reason" type="textarea" :rows="3" placeholder="确认款式映射、原表公式及修订原因" /><el-input v-else v-model="asErp(row).mappingReason" type="textarea" :rows="3" placeholder="按单据/合同/模具ID确认的归属依据" /></template></el-table-column>
      </el-table>
    </template>
    <template #footer><el-button @click="close">取消，不写入</el-button><el-button v-if="preview" type="primary" :loading="busy" :disabled="!options.writable" @click="commit">确认映射并提交</el-button></template>
  </el-dialog>
</template>
<style scoped>.import-source{padding:18px 0;display:grid;gap:12px}p{margin:6px 0}pre{font-size:11px;white-space:pre-wrap}small{color:var(--el-text-color-secondary)}</style>
