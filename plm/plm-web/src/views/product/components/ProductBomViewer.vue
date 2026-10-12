<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { getProductBomSummary } from '@/api/modules/bom'
import type { BomSummary } from '@/types/bom'

const props = defineProps<{ productId: number }>()
const loading = ref(false)
const error = ref('')
const summary = ref<BomSummary | null>(null)
const mode = ref<'test' | 'formal'>('test')
const selectedBomId = ref<number | null>(null)
const selectedRouteId = ref<number | null>(null)

const selectedVersion = computed(() => summary.value?.formalVersions.find((item) => item.productBomId === selectedBomId.value) || summary.value?.formalVersions[0] || null)
const selectedRoute = computed(() => selectedVersion.value?.routes.find((item) => item.productBomRouteId === selectedRouteId.value) || selectedVersion.value?.routes[0] || null)

async function load() {
  loading.value = true
  error.value = ''
  try {
    summary.value = await getProductBomSummary(props.productId)
    selectedBomId.value = summary.value.formalVersions[0]?.productBomId || null
    selectedRouteId.value = summary.value.formalVersions[0]?.routes[0]?.productBomRouteId || null
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : 'BOM 数据加载失败'
  } finally { loading.value = false }
}

function selectVersion() {
  selectedRouteId.value = selectedVersion.value?.routes[0]?.productBomRouteId || null
}

watch(() => props.productId, load, { immediate: true })
</script>

<template>
  <div class="product-bom-viewer" v-loading="loading">
    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" />
    <template v-else>
      <div class="viewer-switch" role="tablist">
        <button :class="{ active: mode === 'test' }" @click="mode = 'test'">测试 BOM 成本</button>
        <button data-test="formal-mode" :class="{ active: mode === 'formal' }" @click="mode = 'formal'">正式 BOM</button>
      </div>
      <div v-if="summary" class="cost-summary-grid">
        <div><span>研发总成本</span><strong>{{ summary.rdTotalCost ?? '--' }}</strong></div>
        <div><span>正式版本平均单个成本</span><strong>{{ summary.formalAverageUnitCost ?? '--' }}</strong></div>
        <div><span>当前 BOM 单个 SKU 成本</span><strong>{{ summary.currentBomSkuUnitCost ?? '--' }}</strong></div>
      </div>

      <section v-if="mode === 'test'" class="viewer-section">
        <template v-if="summary?.testTotalCost != null">
          <div class="test-total"><span>测试阶段最终敲定总成本</span><strong>{{ summary.testTotalCost }}</strong><small>版本 {{ summary.testVersionNo || '--' }} · {{ summary.testCalculatedAt?.slice(0, 16).replace('T', ' ') || '--' }}</small></div>
        </template>
        <el-empty v-else description="暂无测试 BOM" />
      </section>

      <section v-else class="viewer-section">
        <div v-if="summary?.formalVersions.length" class="viewer-controls">
          <el-select v-model="selectedBomId" aria-label="正式 BOM 版本" @change="selectVersion"><el-option v-for="version in summary.formalVersions" :key="version.productBomId" :label="`${version.versionNo} · ${version.bomName}`" :value="version.productBomId" /></el-select>
          <el-select v-model="selectedRouteId" aria-label="工艺路线"><el-option v-for="route in selectedVersion?.routes || []" :key="route.productBomRouteId" :label="route.variantName || route.routeName" :value="route.productBomRouteId" /></el-select>
        </div>
        <template v-if="selectedRoute">
          <div class="route-summary"><div><strong>{{ selectedRoute.variantName || selectedRoute.routeName }}</strong><code>{{ selectedRoute.routeCode }} / {{ selectedRoute.routeVariantNo || 'BASE' }}</code></div><div class="route-colors"><el-tag v-for="color in selectedRoute.colors" :key="color" size="small">{{ color }}</el-tag></div><strong>{{ selectedRoute.costSnapshot ? `${selectedRoute.costSnapshot.currencyCode} ${selectedRoute.skuUnitCost ?? selectedRoute.costSnapshot.totalCost}` : '成本计算失败或尚未计算' }}</strong></div>
          <table><thead><tr><th>行号</th><th>物料编码</th><th>物料名称</th><th>用量</th><th>单位</th><th>损耗率</th></tr></thead><tbody><tr v-for="item in selectedRoute.items" :key="item.productBomItemId || item.lineNo"><td>{{ item.lineNo }}</td><td>{{ item.itemCode || '--' }}</td><td>{{ item.itemName }}</td><td>{{ item.quantity }}</td><td>{{ item.unit }}</td><td>{{ item.lossRate || 0 }}</td></tr></tbody></table>
        </template>
        <el-empty v-else description="暂无正式 BOM 或适用工艺路线" />
      </section>
    </template>
  </div>
</template>

<style scoped>
.viewer-switch { display: inline-grid; grid-template-columns: 1fr 1fr; padding: 3px; border: 1px solid var(--el-border-color); border-radius: 6px; background: var(--el-fill-color-light); }.viewer-switch button { min-width: 140px; padding: 7px 12px; border: 0; border-radius: 4px; background: transparent; cursor: pointer; }.viewer-switch button.active { color: var(--el-color-primary); background: var(--el-bg-color); box-shadow: 0 1px 3px rgb(0 0 0 / 10%); }
.cost-summary-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-top: 12px; }.cost-summary-grid > div { display: grid; gap: 4px; padding: 10px; border: 1px solid var(--el-border-color-lighter); }.cost-summary-grid span { color: var(--plm-color-text-secondary); font-size: 12px; }.viewer-section { margin-top: 14px; }.test-total { display: grid; max-width: 360px; gap: 5px; padding: 14px 0; border-top: 1px solid var(--el-border-color-lighter); border-bottom: 1px solid var(--el-border-color-lighter); }.test-total span, .test-total small, code { color: var(--plm-color-text-secondary); font-size: 12px; }.test-total strong { font-size: 24px; }.viewer-controls { display: flex; gap: 8px; margin-bottom: 12px; }.viewer-controls :deep(.el-select) { width: 260px; }.route-summary { display: grid; grid-template-columns: 1fr 1fr 160px; align-items: center; gap: 12px; padding: 10px 0; border-block: 1px solid var(--el-border-color-lighter); }.route-summary div:first-child { display: grid; }.route-colors { display: flex; flex-wrap: wrap; gap: 4px; }table { width: 100%; border-collapse: collapse; font-size: 13px; }th, td { padding: 9px 10px; border-bottom: 1px solid var(--el-border-color-lighter); text-align: left; }th { background: var(--el-fill-color-lighter); }
@media (max-width: 760px) { .viewer-controls { flex-direction: column; }.viewer-controls :deep(.el-select) { width: 100%; }.route-summary { grid-template-columns: 1fr; } }
</style>
