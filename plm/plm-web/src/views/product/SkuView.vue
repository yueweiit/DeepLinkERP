<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'

import { getProductPresentation } from '@/api/modules/foundation'
import { deleteAttachment, downloadAttachment, getProductAttachments, uploadProductAttachment, type AttachmentVO } from '@/api/modules/attachment'
import { getProductList } from '@/api/modules/product'
import FilePreview from '@/components/FilePreview/index.vue'
import FixedTableViewport from '@/components/FixedTableViewport/index.vue'
import PageContainer from '@/components/PageContainer/index.vue'
import ProjectFlowPanel from '@/components/ProjectFlowPanel/index.vue'
import StatusTag from '@/components/StatusTag/index.vue'
import type {
  FoundationProductRef,
  ProductBomItemRow,
  ProductDetailPresentation,
  ProductDocumentSummary,
  ProductTimelineNode,
  ProductionDocumentPreviewFile,
  SkuProcessRouteRow
} from '@/types/foundation'
import type { ProductSummary } from '@/types/product'
import { formatAmount, formatDate } from '@/utils/format'
import { toInProgressProjectRoute } from '@/utils/projectRoute'

interface SkuDisplayRow extends FoundationProductRef {
  productSpecificCode?: string | null
  phoneModelCode?: string | null
  colorCode?: string | null
  finishedProductCode?: string | null
  displaySkuCode: string
  displayProductLineCode: string
  sampleImageUrl?: string
  sampleImageName?: string
  stockUom?: string
  projectSource?: string
}

type ProductListItem = ProductSummary & {
  createdAt?: string | null
  updatedAt?: string | null
  createdBy?: string | null
}

type SkuPageStage = 'product-home' | 'sku-list'
type SkuDetailSectionKey = 'basic' | 'cost' | 'bom' | 'process' | 'project_flow' | 'production_docs'

const router = useRouter()
const loading = ref(false)
const rows = ref<SkuDisplayRow[]>([])
const pageStage = ref<SkuPageStage>('product-home')
const activeProductId = ref<number | null>(null)
const keyword = ref('')
const selectedSkuIds = ref<number[]>([])
const previewImageVisible = ref(false)
const previewImageUrl = ref('')
const sampleImageMap = ref<Record<number, AttachmentVO[]>>({})
const sampleImageUrls = ref<Record<number, string>>({})
const sampleUploadFile = ref<File | null>(null)
const sampleUploadRemark = ref('')
const sampleUploadLoading = ref(false)
const sampleDeleteLoading = ref<number | null>(null)
const createSkuVisible = ref(false)
const deleteLoading = ref(false)

const detailVisible = ref(false)
const detailLoading = ref(false)
const detailSku = ref<SkuDisplayRow | null>(null)
const detailPresentation = ref<ProductDetailPresentation | null>(null)
const detailBomVersion = ref('')
const activeDetailSection = ref<SkuDetailSectionKey>('basic')

/* 生产资料预览 */
const productionPreviewVisible = ref(false)
const activeProductionDoc = ref<ProductionDocumentPreviewFile | null>(null)

const skuDetailSections = [
  { key: 'basic' as const, label: '基础信息' },
  { key: 'cost' as const, label: '成本' },
  { key: 'bom' as const, label: '当前版本 BOM' },
  { key: 'process' as const, label: '工艺路线' },
  { key: 'project_flow' as const, label: '项目流程' },
  { key: 'production_docs' as const, label: '生产资料' }
]

const productCards = computed(() =>
  rows.value.reduce<SkuDisplayRow[]>((acc, item) => {
    if (item.productType === 'product_line') {
      if (!acc.some((row) => row.productId === item.productId)) acc.push(item)
      return acc
    }
    if (item.parentProductId && !acc.some((row) => row.productId === item.parentProductId)) {
      acc.push({
        ...item,
        productId: item.parentProductId,
        parentProductId: null,
        productCode: item.seriesName || item.productCode,
        displayProductLineCode: item.displayProductLineCode,
        productName: item.seriesName || item.productName,
        productType: 'product_line'
      })
    }
    return acc
  }, [])
)

const activeProduct = computed(() => productCards.value.find((item) => item.productId === activeProductId.value) || null)

const currentSkuRows = computed(() => {
  const search = keyword.value.trim().toLowerCase()
  if (!activeProductId.value) return []

  return rows.value.filter((item) => {
    if (item.productType === 'product_line') return false

    const belongsToProduct =
      item.parentProductId === activeProductId.value ||
      (activeProduct.value && item.seriesName === activeProduct.value.seriesName)

    const keywordMatched =
      !search ||
      item.productCode.toLowerCase().includes(search) ||
      item.displaySkuCode.toLowerCase().includes(search) ||
      item.productName.toLowerCase().includes(search) ||
      item.model.toLowerCase().includes(search) ||
      item.color.toLowerCase().includes(search)

    return belongsToProduct && keywordMatched
  })
})

const detailBomItems = computed<ProductBomItemRow[]>(() => {
  if (!detailPresentation.value || !detailBomVersion.value) return []
  return detailPresentation.value.bomItemsByVersion[detailBomVersion.value] || []
})

const detailBomIsDefaultVersion = computed(
  () => Boolean(detailBomVersion.value) && detailBomVersion.value === detailPresentation.value?.defaultBomVersion
)

const detailProcessRoutes = computed<SkuProcessRouteRow[]>(() => {
  return detailPresentation.value?.processRoutes || []
})

const detailTimelineNodes = computed<ProductTimelineNode[]>(() => {
  return detailPresentation.value?.timeline || []
})

function openProductionDocPreview(doc: ProductDocumentSummary) {
  activeProductionDoc.value = {
    fileId: doc.fileId || '',
    fileName: doc.fileName,
    category: doc.category,
    versionNo: doc.versionNo,
    owner: doc.owner,
    updatedAt: doc.updatedAt,
    status: doc.status,
    previewUrl: doc.previewUrl,
    downloadUrl: doc.downloadUrl
  }
  productionPreviewVisible.value = true
}

function getSkuCount(product: FoundationProductRef) {
  return rows.value.filter(
    (item) =>
      item.productType !== 'product_line' &&
      (item.parentProductId === product.productId || item.seriesName === product.seriesName)
  ).length
}

function getSkuUnit(row: SkuDisplayRow) {
  return row.stockUom || 'pcs'
}

function getProjectSource(row: SkuDisplayRow) {
  return row.projectSource || row.customerName || '内部研发'
}

function getBomRemark(row: ProductBomItemRow) {
  if (row.changeType === 'new') return '新增物料'
  if (row.changeType === 'replace') return '替代料'
  if (row.changeType === 'remove') return '本版本移除'
  if (row.changeType === 'inherit') return '沿用父产品'
  return '--'
}

function getBomLineCost(row: ProductBomItemRow) {
  return Number(row.unitCost || 0) * Number(row.quantity || 0)
}

function openSkuList(productId: number) {
  activeProductId.value = productId
  selectedSkuIds.value = []
  keyword.value = ''
  pageStage.value = 'sku-list'
}

function backToProductHome() {
  activeProductId.value = null
  selectedSkuIds.value = []
  keyword.value = ''
  pageStage.value = 'product-home'
}

function handleSkuSelectionChange(selectedRows: SkuDisplayRow[]) {
  selectedSkuIds.value = selectedRows.map((row) => row.productId)
}

function getSkuSampleImages(row: SkuDisplayRow | null | undefined) {
  if (!row) return []
  return sampleImageMap.value[row.productId] || []
}

function getSkuSampleImageUrl(row: SkuDisplayRow | null | undefined) {
  if (!row) return ''
  return sampleImageUrls.value[row.productId] || row.sampleImageUrl || ''
}

function getSampleImageCount(row: SkuDisplayRow | null | undefined) {
  return getSkuSampleImages(row).length
}

function openPreview(url?: string) {
  previewImageUrl.value = url || ''
  previewImageVisible.value = true
}

async function openAttachmentPreview(attachment: AttachmentVO) {
  const url = sampleImageUrls.value[attachment.ownerObjectId]
  if (url && getSkuSampleImages(detailSku.value)[0]?.attachmentId === attachment.attachmentId) {
    openPreview(url)
    return
  }
  const blob = await downloadAttachment(attachment.attachmentId)
  const objectUrl = URL.createObjectURL(blob)
  openPreview(objectUrl)
}

async function refreshSkuSampleImages(productId: number) {
  const images = await getProductAttachments(productId, 'sample_image')
  sampleImageMap.value = { ...sampleImageMap.value, [productId]: images }
  if (!images.length) {
    sampleImageUrls.value = { ...sampleImageUrls.value, [productId]: '' }
    return
  }
  const blob = await downloadAttachment(images[0].attachmentId)
  sampleImageUrls.value = { ...sampleImageUrls.value, [productId]: URL.createObjectURL(blob) }
}

async function refreshVisibleSampleImages() {
  const imageRows = rows.value.filter((item) => item.productType !== 'product_line')
  await Promise.all(imageRows.slice(0, 40).map((item) => refreshSkuSampleImages(item.productId).catch(() => undefined)))
}

function handleSampleUploadFileChange(event: Event) {
  sampleUploadFile.value = (event.target as HTMLInputElement).files?.[0] || null
}

async function submitSampleImageUpload() {
  if (!detailSku.value) return
  if (!sampleUploadFile.value) {
    ElMessage.warning('请选择要上传的示例照片')
    return
  }
  sampleUploadLoading.value = true
  try {
    await uploadProductAttachment(detailSku.value.productId, sampleUploadFile.value, {
      fileCategory: 'sample_image',
      remark: sampleUploadRemark.value.trim() || 'SKU示例照片'
    })
    sampleUploadFile.value = null
    sampleUploadRemark.value = ''
    await refreshSkuSampleImages(detailSku.value.productId)
    ElMessage.success('示例照片已上传')
  } finally {
    sampleUploadLoading.value = false
  }
}

async function removeSampleImage(attachment: AttachmentVO) {
  await ElMessageBox.confirm(`确认删除“${attachment.originalFileName || attachment.fileName}”吗？`, '删除示例照片', {
    confirmButtonText: '删除',
    cancelButtonText: '取消',
    type: 'warning'
  })
  sampleDeleteLoading.value = attachment.attachmentId
  try {
    await deleteAttachment(attachment.attachmentId)
    await refreshSkuSampleImages(attachment.ownerObjectId)
    ElMessage.success('示例照片已删除')
  } finally {
    sampleDeleteLoading.value = null
  }
}

function deleteSelectedSkus() {
  deleteLoading.value = true
  try {
    rows.value = rows.value.filter((row) => !selectedSkuIds.value.includes(row.productId))
    selectedSkuIds.value = []
  } finally {
    deleteLoading.value = false
  }
}

async function openSkuDetail(row: SkuDisplayRow) {
  detailSku.value = row
  activeDetailSection.value = 'basic'
  detailVisible.value = true
  detailLoading.value = true

  try {
    const presentation = await getProductPresentation(row.productId)
    detailPresentation.value = presentation
    detailBomVersion.value = presentation.defaultBomVersion || presentation.bomCompareRows[0]?.versionNo || ''
  } catch {
    detailPresentation.value = null
    detailBomVersion.value = ''
  } finally {
    detailLoading.value = false
  }
}

function resolveDisplaySkuCode(product: ProductListItem) {
  return product.finishedProductCode || product.productCode || ''
}

function resolveDisplayProductLineCode(product: ProductListItem) {
  const productCode = product.productCode || ''
  if (product.productType !== 'product_line' || !productCode.startsWith('PRD-')) {
    return productCode
  }
  const productSpecificCode = product.productSpecificCode?.trim().toUpperCase()
  return productSpecificCode ? `N${productSpecificCode}4030` : productCode
}

function toSkuDisplayRow(product: ProductListItem): SkuDisplayRow {
  return {
    productId: product.productId,
    parentProductId: product.parentProductId ?? null,
    productCode: product.productCode || '',
    productSpecificCode: product.productSpecificCode || null,
    phoneModelCode: product.phoneModelCode || null,
    colorCode: product.colorCode || null,
    finishedProductCode: product.finishedProductCode || null,
    displaySkuCode: resolveDisplaySkuCode(product),
    displayProductLineCode: resolveDisplayProductLineCode(product),
    productName: product.productName || '',
    productType: product.productType || 'model_variant',
    seriesName: product.seriesName || '--',
    model: product.model || '--',
    color: product.color || '--',
    customerName: product.customerName || '',
    versionNo: product.versionNo || 'A',
    status: product.status || 'draft',
    currentStage: product.currentStage || product.status || '--',
    estimatedCost: product.estimatedCost || 0,
    actualCost: product.actualCost || 0,
    lastActiveAt: product.updatedAt || product.createdAt || '',
    createdAt: product.createdAt || '',
    stockUom: 'pcs',
    projectSource: product.createdBy || product.customerName || '历史存档'
  }
}

async function loadData() {
  loading.value = true
  try {
    const results = await Promise.allSettled([
      getProductList({ page: 1, size: 200, productType: 'product_line' }),
      getProductList({ page: 1, size: 200, productType: 'model_variant' }),
      getProductList({ page: 1, size: 200, productType: 'sku' }),
      getProductList({ page: 1, size: 200, status: 'released' }),
      getProductList({ page: 1, size: 200, status: 'archived' })
    ])
    const mergedProducts = new Map<number, ProductListItem>()
    results.forEach((result) => {
      if (result.status === 'fulfilled') {
        result.value.forEach((item) => mergedProducts.set(item.productId, item))
      }
    })
    rows.value = Array.from(mergedProducts.values()).map(toSkuDisplayRow)
    await refreshVisibleSampleImages()
  } catch {
    rows.value = []
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>

<template>
  <PageContainer
    title="SKU 管理"
    description="先按产品卡片定位，再进入该产品下的 SKU 列表进行管理。"
  >
    <section v-if="pageStage === 'product-home'" class="page-panel sku-product-home">
      <div class="toolbar-row sku-product-home__head">
        <div>
          <h3 class="section-title">产品入口</h3>
          <p class="page-panel-desc">SKU 作为 Product 的型号、颜色和版本视图展示，不作为独立根对象。</p>
        </div>
        <el-button type="primary" @click="router.push(toInProgressProjectRoute())">新项目</el-button>
      </div>

      <div class="sku-product-grid" v-loading="loading">
        <button
          v-for="product in productCards"
          :key="product.productId"
          class="sku-product-card"
          type="button"
          @click="openSkuList(product.productId)"
        >
          <div class="sku-product-card__image">
            <span>{{ product.seriesName }}</span>
          </div>
          <div class="toolbar-row">
            <strong>{{ product.productName }}</strong>
            <StatusTag :status="product.status" object-type="product" />
          </div>
          <p class="subtle-text">{{ product.displayProductLineCode }}</p>
          <p class="sku-product-card__series">{{ product.seriesName }}</p>
          <div class="sku-product-card__meta">
            <span>{{ getSkuCount(product) }} 个 SKU</span>
            <span class="subtle-text">更新 {{ formatDate(product.lastActiveAt) }}</span>
          </div>
        </button>
      </div>
    </section>

    <section v-else class="page-panel sku-list-panel" v-loading="loading">
      <div class="toolbar-row sku-list-panel__head">
        <div>
          <el-button link type="primary" @click="backToProductHome">返回产品卡片</el-button>
          <h3 class="section-title">{{ activeProduct?.productName }} / SKU 列表</h3>
          <p class="page-panel-desc">查看当前产品下的 SKU 信息、示例图、版本状态和详情资料。</p>
        </div>

        <div class="sku-list-panel__actions">
          <el-input
            v-model="keyword"
            clearable
            class="sku-list-panel__search"
            placeholder="搜索编码 / 名称 / 型号 / 颜色"
          />
          <el-button type="primary" @click="createSkuVisible = true">新增 SKU</el-button>
          <el-button
            type="danger"
            :disabled="!selectedSkuIds.length"
            :loading="deleteLoading"
            @click="deleteSelectedSkus"
          >
            删除 SKU
          </el-button>
        </div>
      </div>

      <FixedTableViewport v-slot="{ tableHeight }" :refresh-key="currentSkuRows">
      <el-table :data="currentSkuRows" :height="tableHeight" border stripe @selection-change="handleSkuSelectionChange">
        <el-table-column type="selection" width="48" />
        <el-table-column label="示例图" min-width="150">
          <template #default="{ row }">
            <div class="sku-image-cell">
              <div class="sku-image-cell__thumb">
                <el-image v-if="getSkuSampleImageUrl(row)" :src="getSkuSampleImageUrl(row)" fit="cover" />
                <span v-else>{{ row.model }}</span>
              </div>
              <div class="sku-image-cell__actions">
                <el-button link type="primary" :disabled="!getSkuSampleImageUrl(row)" @click="openPreview(getSkuSampleImageUrl(row))">查看示例图</el-button>
                <span class="subtle-text">{{ getSampleImageCount(row) }} 张</span>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="displaySkuCode" label="SKU 编码" min-width="180" />
        <el-table-column prop="productName" label="SKU 名称" min-width="220" />
        <el-table-column prop="model" label="型号" width="140" />
        <el-table-column label="单位" width="80">
          <template #default="{ row }">{{ getSkuUnit(row) }}</template>
        </el-table-column>
        <el-table-column label="项目来源" min-width="150">
          <template #default="{ row }">{{ getProjectSource(row) }}</template>
        </el-table-column>
        <el-table-column prop="color" label="颜色" width="120" />
        <el-table-column prop="versionNo" label="版本" width="100" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <StatusTag :status="row.status" object-type="product" />
          </template>
        </el-table-column>
        <el-table-column label="最近更新时间" width="140">
          <template #default="{ row }">{{ formatDate(row.lastActiveAt) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openSkuDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
      </FixedTableViewport>
    </section>

    <el-dialog v-model="detailVisible" title="SKU 详情" width="1080px" destroy-on-close>
      <div v-loading="detailLoading" class="sku-detail-dialog">
        <nav class="sku-detail-breadcrumb" aria-label="SKU 详情导航">
          <span class="sku-detail-breadcrumb__root">SKU 详情</span>
          <template v-for="section in skuDetailSections" :key="section.key">
            <span class="sku-detail-breadcrumb__separator">/</span>
            <button
              class="sku-detail-breadcrumb__item"
              :class="{ 'is-active': activeDetailSection === section.key }"
              type="button"
              @click="activeDetailSection = section.key"
            >
              {{ section.label }}
            </button>
          </template>
        </nav>

        <section v-show="activeDetailSection === 'basic'" class="sku-detail-section">
          <h4 class="section-title">基础信息</h4>
          <div class="sku-detail-grid">
            <div class="info-card"><span class="subtle-text">SKU 编码</span><strong>{{ detailSku?.displaySkuCode }}</strong></div>
            <div class="info-card"><span class="subtle-text">SKU 名称</span><strong>{{ detailSku?.productName }}</strong></div>
            <div class="info-card"><span class="subtle-text">Product 编码</span><strong>{{ detailSku?.productCode }}</strong></div>
            <div class="info-card"><span class="subtle-text">产品线</span><strong>{{ detailSku?.seriesName }}</strong></div>
            <div class="info-card"><span class="subtle-text">型号</span><strong>{{ detailSku?.model }}</strong></div>
            <div class="info-card"><span class="subtle-text">手机型号编码</span><strong>{{ detailSku?.phoneModelCode || '--' }}</strong></div>
            <div class="info-card"><span class="subtle-text">单位</span><strong>{{ detailSku ? getSkuUnit(detailSku) : '--' }}</strong></div>
            <div class="info-card"><span class="subtle-text">项目来源</span><strong>{{ detailSku ? getProjectSource(detailSku) : '--' }}</strong></div>
            <div class="info-card"><span class="subtle-text">颜色</span><strong>{{ detailSku?.color }}</strong></div>
            <div class="info-card"><span class="subtle-text">颜色编码</span><strong>{{ detailSku?.colorCode || '--' }}</strong></div>
            <div class="info-card"><span class="subtle-text">版本</span><strong>{{ detailSku?.versionNo }}</strong></div>
            <div class="info-card">
              <span class="subtle-text">状态</span>
              <StatusTag v-if="detailSku" :status="detailSku.status" object-type="product" />
            </div>
          </div>

          <div class="sku-sample-panel">
            <div class="sku-detail-section__head">
              <div>
                <h5>示例照片</h5>
                <p class="page-panel-desc">照片以 Product 附件保存，文件分类为 sample_image。</p>
              </div>
              <el-tag effect="light">{{ getSampleImageCount(detailSku) }} 张</el-tag>
            </div>

            <div class="sku-sample-upload">
              <input data-test="sku-sample-upload-file" type="file" accept="image/jpeg,image/png,image/webp" @change="handleSampleUploadFileChange" />
              <el-input v-model="sampleUploadRemark" clearable maxlength="255" placeholder="照片备注" />
              <el-button type="primary" :loading="sampleUploadLoading" @click="submitSampleImageUpload">上传照片</el-button>
            </div>

            <div v-if="getSkuSampleImages(detailSku).length" class="sku-sample-gallery">
              <article v-for="image in getSkuSampleImages(detailSku)" :key="image.attachmentId" class="sku-sample-gallery__item">
                <button type="button" class="sku-sample-gallery__preview" @click="openAttachmentPreview(image)">
                  <el-image v-if="sampleImageUrls[image.ownerObjectId] && getSkuSampleImages(detailSku)[0]?.attachmentId === image.attachmentId" :src="sampleImageUrls[image.ownerObjectId]" fit="cover" />
                  <span v-else>{{ image.originalFileName || image.fileName }}</span>
                </button>
                <div class="sku-sample-gallery__meta">
                  <strong>{{ image.originalFileName || image.fileName }}</strong>
                  <span class="subtle-text">{{ image.remark || '无备注' }}</span>
                </div>
                <el-button link type="danger" :loading="sampleDeleteLoading === image.attachmentId" @click="removeSampleImage(image)">删除</el-button>
              </article>
            </div>
            <el-empty v-else description="暂无示例照片" />
          </div>
        </section>

        <section v-show="activeDetailSection === 'cost'" class="sku-detail-section">
          <h4 class="section-title">成本</h4>
          <div class="sku-detail-cost-grid">
            <div class="info-card">
              <span class="subtle-text">实际成本</span>
              <strong>{{ formatAmount(detailPresentation?.costPanel.actualTotal || 0) }}</strong>
            </div>
            <div v-if="detailPresentation?.costPanel.showEstimated" class="info-card">
              <span class="subtle-text">预计成本</span>
              <strong>{{ formatAmount(detailPresentation?.costPanel.estimatedTotal || 0) }}</strong>
            </div>
            <div class="info-card">
              <span class="subtle-text">当前阶段</span>
              <strong>{{ detailSku?.currentStage }}</strong>
            </div>
          </div>
        </section>

        <section v-show="activeDetailSection === 'bom'" class="sku-detail-section">
          <div class="sku-detail-section__head">
            <div>
              <div class="sku-detail-title-row">
                <h4 class="section-title">当前版本 BOM</h4>
                <el-tag v-if="detailBomIsDefaultVersion" type="success" effect="light" size="small">正式版本</el-tag>
              </div>
              <p class="page-panel-desc">BOM 作为 Product 的版本化资料展示，不作为独立根对象。</p>
            </div>
            <el-select v-model="detailBomVersion" class="sku-detail-version-select" placeholder="选择 BOM 版本">
              <el-option
                v-for="row in detailPresentation?.bomCompareRows || []"
                :key="row.versionNo"
                :label="row.versionNo"
                :value="row.versionNo"
              />
            </el-select>
          </div>

          <el-table :data="detailBomItems" border stripe>
            <el-table-column prop="inventoryCode" label="物料编码" min-width="150" />
            <el-table-column prop="inventoryName" label="物料名称" min-width="180" />
            <el-table-column prop="quantity" label="用量" width="90" />
            <el-table-column prop="stockUom" label="单位" width="90" />
            <el-table-column prop="supplierName" label="供应商" min-width="150" />
            <el-table-column label="备注 / 替代料提示" min-width="170">
              <template #default="{ row }">{{ getBomRemark(row) }}</template>
            </el-table-column>
            <el-table-column label="成本" width="130">
              <template #default="{ row }">{{ formatAmount(getBomLineCost(row)) }}</template>
            </el-table-column>
          </el-table>
        </section>

        <section v-show="activeDetailSection === 'process'" class="sku-detail-section">
          <div class="sku-detail-section__head">
            <div>
              <h4 class="section-title">工艺路线</h4>
              <p class="page-panel-desc">工艺路线由 Process 承接，以工序明细表展示当前 SKU 的完整工序、关联模具和检验要求。</p>
            </div>
            <el-tag type="primary" effect="light">共 {{ detailProcessRoutes.length }} 道工序</el-tag>
          </div>

          <el-table v-if="detailProcessRoutes.length" :data="detailProcessRoutes" border stripe size="small">
            <el-table-column label="顺序" width="60">
              <template #default="{ row }">{{ row.sequenceNo }}</template>
            </el-table-column>
            <el-table-column prop="processCode" label="工序编码" min-width="150" />
            <el-table-column prop="processName" label="工序名称" min-width="130" />
            <el-table-column label="工序类型" width="110">
              <template #default="{ row }">
                <el-tag :type="row.processType === 'quality_gate' ? 'danger' : 'primary'" effect="light" size="small">
                  {{ row.processType === 'quality_gate' ? '质量门禁' : '加工工序' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="模具 / 治具" min-width="160">
              <template #default="{ row }">
                <template v-if="row.inventoryCode">
                  <div>{{ row.inventoryCode }}</div>
                  <span class="subtle-text" style="font-size:12px">{{ row.inventoryName }}</span>
                </template>
                <span v-else class="subtle-text">--</span>
              </template>
            </el-table-column>
            <el-table-column label="执行位置" min-width="130">
              <template #default="{ row }">{{ row.workstationName || '--' }}</template>
            </el-table-column>
            <el-table-column label="供应商" min-width="120">
              <template #default="{ row }">{{ row.supplierName || '--' }}</template>
            </el-table-column>
            <el-table-column label="质量要求" min-width="180">
              <template #default="{ row }">{{ row.qualityRequirement || '--' }}</template>
            </el-table-column>
            <el-table-column label="产出类型" width="100">
              <template #default="{ row }">{{ row.outputType || '--' }}</template>
            </el-table-column>
            <el-table-column prop="summary" label="说明" min-width="200" />
          </el-table>
          <el-empty v-else description="暂无工艺路线数据" />
        </section>

        <section v-show="activeDetailSection === 'project_flow'" class="sku-detail-section">
          <div class="sku-detail-section__head">
            <div>
              <h4 class="section-title">项目流程</h4>
              <p class="page-panel-desc">展示当前 SKU 对应 Product 的项目流程节点、接收人与推动记录。</p>
            </div>
          </div>

          <ProjectFlowPanel
            v-if="detailTimelineNodes.length"
            :nodes="detailTimelineNodes"
            :compact="true"
            :max-nodes="8"
          />
          <el-empty v-else description="暂无项目流程数据" />
        </section>

        <section v-show="activeDetailSection === 'production_docs'" class="sku-detail-section">
          <div class="sku-detail-section__head">
            <div>
              <h4 class="section-title">生产资料</h4>
              <p class="page-panel-desc">展示归档或当前版本关联的图纸、SOP、SIP、检验标准和客户确认件。</p>
            </div>
          </div>

          <el-table v-if="detailPresentation?.documents?.length" :data="detailPresentation.documents" border stripe size="small">
            <el-table-column label="资料类型" width="120">
              <template #default="{ row }">{{ row.category }}</template>
            </el-table-column>
            <el-table-column label="资料编码" width="140">
              <template #default="{ row }">{{ row.fileId || '--' }}</template>
            </el-table-column>
            <el-table-column prop="fileName" label="资料名称" min-width="200" />
            <el-table-column prop="versionNo" label="版本" width="90" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag v-if="row.status" size="small" effect="light" :type="row.status === '已冻结' ? 'success' : row.status === '已归档' ? 'info' : 'warning'">
                  {{ row.status }}
                </el-tag>
                <span v-else class="subtle-text">--</span>
              </template>
            </el-table-column>
            <el-table-column label="负责人" width="110">
              <template #default="{ row }">{{ row.owner || '--' }}</template>
            </el-table-column>
            <el-table-column label="所属阶段" width="120">
              <template #default="{ row }">{{ row.stageLabel || row.category }}</template>
            </el-table-column>
            <el-table-column label="更新时间" width="130">
              <template #default="{ row }">{{ formatDate(row.updatedAt) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="130" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="openProductionDocPreview(row)">预览</el-button>
                <el-button link type="primary" size="small">下载</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="暂无生产资料" />
        </section>
      </div>
      <!-- 生产资料预览 -->
      <FilePreview
        v-model="productionPreviewVisible"
        :file="activeProductionDoc"
      />
    </el-dialog>

    <el-dialog v-model="previewImageVisible" title="SKU 示例图" width="640px">
      <el-image v-if="previewImageUrl" :src="previewImageUrl" fit="contain" class="sku-preview-image" />
      <p v-else class="subtle-text empty-preview">暂无示例图</p>
    </el-dialog>
  </PageContainer>
</template>

<style scoped>
.sku-product-home__head {
  margin-bottom: 14px;
}

.sku-product-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.sku-product-card {
  display: flex;
  min-height: 220px;
  flex-direction: column;
  gap: 10px;
  padding: 16px;
  border: 1px solid var(--plm-color-border-light);
  border-radius: var(--plm-radius-base);
  background: #fff;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.16s ease, box-shadow 0.16s ease, transform 0.16s ease;
}

.sku-product-card:hover {
  border-color: var(--plm-color-primary);
  box-shadow: var(--plm-shadow-md);
  transform: translateY(-1px);
}

.sku-product-card__image,
.sku-image-cell__thumb {
  display: grid;
  place-items: center;
  border-radius: 8px;
  background: linear-gradient(135deg, #e9eef8 0%, #f8fafc 100%);
  color: #3b4a63;
  font-weight: 600;
}

.sku-product-card__image {
  min-height: 100px;
}

.sku-product-card__series {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.sku-product-card__meta,
.sku-list-panel__actions,
.sku-image-cell,
.sku-detail-section__head,
.sku-detail-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.sku-product-card__meta {
  justify-content: space-between;
  margin-top: auto;
}

.sku-list-panel__head {
  align-items: flex-start;
  margin-bottom: 14px;
}

.sku-list-panel__actions {
  flex-shrink: 0;
}

.sku-list-panel__search {
  width: 260px;
}

.sku-image-cell__thumb {
  width: 52px;
  height: 52px;
  overflow: hidden;
  font-size: 11px;
}

.sku-image-cell__thumb :deep(.el-image),
.sku-image-cell__thumb :deep(img) {
  width: 100%;
  height: 100%;
}

.sku-image-cell__actions {
  display: flex;
  min-width: 0;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
}

.sku-sample-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-top: 4px;
}

.sku-sample-panel h5 {
  margin: 0;
  font-size: 14px;
}

.sku-sample-upload {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) minmax(220px, 1.2fr) auto;
  gap: 10px;
  align-items: center;
}

.sku-sample-upload input[type="file"] {
  min-height: 32px;
}

.sku-sample-gallery {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.sku-sample-gallery__item {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 8px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
}

.sku-sample-gallery__preview {
  display: grid;
  place-items: center;
  width: 72px;
  height: 72px;
  overflow: hidden;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #f8fafc;
  color: #64748b;
  cursor: pointer;
  font-size: 12px;
}

.sku-sample-gallery__preview :deep(.el-image),
.sku-sample-gallery__preview :deep(img) {
  width: 100%;
  height: 100%;
}

.sku-sample-gallery__meta {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.sku-sample-gallery__meta strong,
.sku-sample-gallery__meta span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sku-detail-dialog {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.sku-detail-breadcrumb {
  display: flex;
  align-items: center;
  gap: 0;
  padding-bottom: 14px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.2);
}

.sku-detail-breadcrumb__root {
  margin-right: 6px;
  color: #0f172a;
  font-size: 14px;
  font-weight: 600;
}

.sku-detail-breadcrumb__separator {
  margin: 0 4px;
  color: #94a3b8;
  font-size: 13px;
}

.sku-detail-breadcrumb__item {
  padding: 4px 8px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: #64748b;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.16s, color 0.16s;
}

.sku-detail-breadcrumb__item:hover {
  background: #f1f5f9;
  color: #334155;
}

.sku-detail-breadcrumb__item.is-active {
  background: #eff6ff;
  color: #1d4ed8;
  font-weight: 600;
}

.sku-detail-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.sku-detail-section__head {
  align-items: flex-start;
  justify-content: space-between;
}

.sku-detail-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.sku-detail-cost-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.sku-detail-version-select {
  width: 170px;
}

.sku-preview-image {
  width: 100%;
  max-height: 70vh;
}

.empty-preview {
  padding: 40px;
  text-align: center;
}

@media (max-width: 1400px) {
  .sku-product-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 1100px) {
  .sku-product-grid,
  .sku-detail-grid,
  .sku-detail-cost-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .sku-product-grid,
  .sku-detail-grid,
  .sku-detail-cost-grid {
    grid-template-columns: 1fr;
  }

  .sku-list-panel__actions,
  .sku-detail-section__head {
    width: 100%;
    flex-direction: column;
    align-items: stretch;
  }

  .sku-list-panel__search,
  .sku-detail-version-select {
    width: 100%;
  }
}
</style>








