import type { CommonStatus } from './common'

export interface FoundationProductRef {
  productId: number
  productCode: string
  productName: string
  seriesName: string
  model: string
  color: string
  customerName: string
  productType: 'product_line' | 'model_variant' | 'sku'
  parentProductId?: number | null
  versionNo: string
  status: CommonStatus
  currentStage: string
  estimatedCost: number
  actualCost: number
  lastActiveAt: string
  createdAt: string
}

export interface CostLine {
  label: string
  amount: number
  note: string
}

export interface ProductCostPanel {
  showEstimated: boolean
  estimatedTotal?: number
  estimatedLines?: CostLine[]
  actualTotal: number
  actualLines: CostLine[]
}

export interface BomCompareRow {
  versionNo: string
  statusLabel: string
  materialCost: number
  processCost: number
  totalCost: number
  delta: number
}

export interface BomCostSummary {
  materialCost: number
  processCost: number
  packageCost: number
  laborCost: number
  toolingCost: number
  lossCost: number
  totalCost: number
}

export interface ProductBomItemRow {
  inventoryCode: string
  inventoryName: string
  quantity: number
  stockUom: string
  supplierName: string
  unitCost: number
  changeType?: 'new' | 'replace' | 'inherit' | 'remove'
}

export type ProductBomItemsByVersion = Record<string, ProductBomItemRow[]>

export interface ProductTimelineNode {
  nodeKey: string
  nodeName: string
  status: 'completed' | 'current' | 'pending' | 'rejected'
  ownerRole: string
  plannedDate?: string
  actualDate?: string
  summary: string
  nextAction?: string
  riskNote?: string
  canAdvance?: boolean
  canReject?: boolean
  gateLabel?: string
  detailLines?: string[]

  /* 项目流程模块扩展字段 */
  receiverRole?: string
  receiverUserName?: string
  receivedAt?: string
  promoterRole?: string
  promoterUserName?: string
  promotedAt?: string
  experienceSummary?: string
  documentCount?: number
  phaseName?: string
  stageCode?: string | null
  stageName?: string | null
  requiredFileCategory?: string | null
  nextReceiverRole?: string
  nextReceiverUserName?: string
}

export interface ProductMaterialCategoryItem {
  itemCode: string
  itemName: string
  spec: string
  supplierName: string
  note: string
}

export interface ProductMaterialCategory {
  categoryKey: string
  categoryName: string
  items: ProductMaterialCategoryItem[]
}

export interface ProductToolingSummary {
  totalCount: number
  availableCount: number
  trialCount: number
  toolingNames: string[]
  targetPath?: string
}

export interface ProductSupplierSummary {
  supplierName: string
  role: string
  statusLabel: string
  note: string
}

export interface ProductDocumentSummary {
  fileId?: string
  fileName: string
  category: string
  versionNo: string
  updatedAt: string
  owner?: string
  status?: string
  previewUrl?: string
  downloadUrl?: string
  stageKey?: string
  stageLabel?: string
}

export interface ProductQualitySummary {
  testItem: string
  resultLabel: string
  owner: string
  testedAt: string
  note: string
}

export interface ProductDetailPresentation {
  productId: number
  title: string
  flowLabel: string
  currentNode: string
  nextNode: string
  summary: string
  costPanel: ProductCostPanel
  timeline: ProductTimelineNode[]
  bomCompareRows: BomCompareRow[]
  bomCostSummary?: BomCostSummary
  bomItems: ProductBomItemRow[]
  bomItemsByVersion: ProductBomItemsByVersion
  defaultBomVersion?: string
  toolingSummary: ProductToolingSummary
  materialCategories: ProductMaterialCategory[]
  suppliers: ProductSupplierSummary[]
  documents: ProductDocumentSummary[]
  qualityRecords: ProductQualitySummary[]
  processRoutes?: SkuProcessRouteRow[]
}

export interface FileRecord {
  fileId: string
  fileName: string
  category: string
  owner: string
  uploadedAt: string
  versionNo: string
  productId: number
  stageKey?: string
  stageLabel?: string
}

export interface FileProjectGroup {
  groupId: string
  projectName: string
  productCode: string
  productId: number
  owner: string
  updatedAt: string
  productType?: 'product' | 'variant'
  files: FileRecord[]
}

export type FileDateRange = '7d' | '30d' | '180d'

export type FileProductTypeFilter = 'all' | 'product' | 'variant'

export interface FileSection {
  key: 'product_files' | 'variant_files'
  title: string
  description: string
  groups: FileProjectGroup[]
}

export interface TestCategoryItem {
  categoryId: string
  categoryName: string
  method: string
  defaultFrequency: string
  owner: string
}

export interface TestRecordItem {
  recordId: string
  productId: number
  productName: string
  testCategory: string
  result: '通过' | '不通过' | '复测中'
  owner: string
  testedAt: string
  note: string
}

export type InventoryTreeNodeType = 'category' | 'product' | 'product-group' | 'product-model' | 'tooling-group' | 'tooling-leaf'

export interface InventoryTreeNode {
  nodeId: string
  label: string
  nodeType: InventoryTreeNodeType
  count?: number
  groupCode?: string
  children?: InventoryTreeNode[]
}

export interface InventoryListRow {
  itemId: string
  nodeId: string
  code: string
  name: string
  spec: string
  stock: string
  inventoryType: string
  productName?: string
  phoneModel?: string
  status: 'draft' | 'available' | 'reserved' | 'consumed' | 'closed' | 'in_use'
  supplierName: string
  updatedAt: string
  projectDate?: string
}

export interface InventoryItemCreatePayload {
  nodeId: string
  productName?: string
  phoneModel?: string
  item_code: string
  item_name: string
  item_group: string
  stock_uom: string
  custom_specifications?: string
  custom_external_code?: string
  custom_short_name?: string
  custom_mnemonic_code?: string
  custom_dpci?: string
  is_stock_item?: 0 | 1
  is_sales_item?: 0 | 1
  is_purchase_item?: 0 | 1
}

export interface BomCenterRow {
  productId: number
  productCode: string
  productName: string
  bomType: 'EBOM' | 'MBOM' | 'PACK'
  currentVersion: string
  status: CommonStatus
  materialCost: number
  processCost: number
  totalCost: number
  supplierNote: string
  updatedAt: string
}

/* ========== 项目流程模块类型 ========== */

export type ProjectFlowStatus = 'completed' | 'current' | 'pending' | 'rejected'

export interface ProjectFlowNode {
  stepNo: number
  nodeKey: string
  nodeName: string
  phaseName: string
  status: ProjectFlowStatus
  experienceSummary: string
  receiverRole: string
  receiverUserName?: string
  receivedAt?: string
  promoterRole: string
  promoterUserName?: string
  promotedAt?: string
  plannedAt?: string
  nextAction?: string
  nextReceiverRole?: string
  nextReceiverUserName?: string
  gateLabel?: string
  riskNote?: string
  detailLines?: string[]
  documentCount?: number
}

/* ========== 生产资料预览组件类型 ========== */

export interface ProductionDocumentPreviewFile {
  fileId: string
  fileName: string
  category: string
  versionNo: string
  owner?: string
  updatedAt?: string
  status?: string
  previewUrl?: string
  downloadUrl?: string
}

/* ========== SKU 工艺路线工序行 ========== */

export interface SkuProcessRouteRow {
  sequenceNo: number
  processCode: string
  processName: string
  processType: string
  inventoryCode?: string | null
  inventoryName?: string | null
  workstationName?: string | null
  supplierName?: string | null
  qualityRequirement?: string
  outputType?: string
  summary?: string
}
