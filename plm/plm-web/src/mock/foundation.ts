import { mockResolve } from '@/api/request'
import type {
  BomCenterRow,
  FileSection,
  FoundationProductRef,
  InventoryListRow,
  InventoryTreeNode,
  ProductDetailPresentation,
  SkuProcessRouteRow,
  TestCategoryItem,
  TestRecordItem
} from '@/types/foundation'

export const foundationProducts: FoundationProductRef[] = [
  {
    productId: 101,
    productCode: 'PRD-CD30-001',
    productName: '超队 3.0 磁吸手机壳',
    seriesName: '超队 3.0',
    model: 'iPhone 17',
    color: '曜石黑',
    customerName: '北美渠道 A',
    productType: 'product_line',
    versionNo: 'A.3',
    status: 'developing',
    currentStage: '红样测试',
    estimatedCost: 35,
    actualCost: 32.3,
    lastActiveAt: '2026-06-08',
    createdAt: '2026-05-20'
  },
  {
    productId: 102,
    productCode: 'PRD-CD30-IP18-BLK',
    productName: '超队 3.0 iPhone18 黑色',
    seriesName: '超队 3.0',
    model: 'iPhone 18',
    color: '黑色',
    customerName: '北美渠道 A',
    productType: 'model_variant',
    parentProductId: 101,
    versionNo: 'A.2',
    status: 'developing',
    currentStage: '差异测试验证',
    estimatedCost: 0,
    actualCost: 12.3,
    lastActiveAt: '2026-06-09',
    createdAt: '2026-06-02'
  },
  {
    productId: 103,
    productCode: 'PRD-CD30-IP18-BLU',
    productName: '超队 3.0 iPhone18 蓝色',
    seriesName: '超队 3.0',
    model: 'iPhone 18',
    color: '深海蓝',
    customerName: '北美渠道 A',
    productType: 'model_variant',
    parentProductId: 101,
    versionNo: 'A.1',
    status: 'developing',
    currentStage: '样品确认',
    estimatedCost: 0,
    actualCost: 11.8,
    lastActiveAt: '2026-06-06',
    createdAt: '2026-06-03'
  },
  {
    productId: 104,
    productCode: 'PRD-LJ30-001',
    productName: '亮甲 3.0 镜面手机壳',
    seriesName: '亮甲 3.0',
    model: 'iPhone 18',
    color: '樱花粉',
    customerName: '日本零售客户',
    productType: 'product_line',
    versionNo: 'B.1',
    status: 'released',
    currentStage: '正式发布',
    estimatedCost: 36.2,
    actualCost: 33.5,
    lastActiveAt: '2026-05-29',
    createdAt: '2026-04-18'
  },
  {
    productId: 105,
    productCode: 'PRD-LJ30-IP18-GLD',
    productName: '亮甲 3.0 iPhone18 金色',
    seriesName: '亮甲 3.0',
    model: 'iPhone 18',
    color: '香槟金',
    customerName: '日本零售客户',
    productType: 'model_variant',
    parentProductId: 104,
    versionNo: 'A.1',
    status: 'released',
    currentStage: '正式发布',
    estimatedCost: 0,
    actualCost: 13.1,
    lastActiveAt: '2026-05-18',
    createdAt: '2026-05-06'
  }
]

function clone<T>(value: T): T {
  return structuredClone(value)
}

export const productDetailPresentationMap: Record<number, ProductDetailPresentation> = {
  101: {
    productId: 101,
    title: '超队 3.0 磁吸手机壳',
    flowLabel: '新产品线',
    currentNode: '红样测试',
    nextNode: '整理生产资料',
    summary: '当前围绕完整新产品线流程推进，重点收口红样测试、BOM 版本确认和生产资料冻结准备。',
    costPanel: {
      showEstimated: true,
      estimatedTotal: 35,
      estimatedLines: [
        { label: '材料成本', amount: 12.8, note: 'TPU 主材、PC 背板、磁吸组件' },
        { label: '模具成本', amount: 9.6, note: '注塑模与修模分摊' },
        { label: '工艺加工', amount: 6.1, note: '喷油、贴磁、组装与全检' },
        { label: '包装测试', amount: 3.2, note: '彩盒、标签与跌落测试' },
        { label: '损耗预估', amount: 3.3, note: '试产损耗与波动缓冲' }
      ],
      actualTotal: 32.3,
      actualLines: [
        { label: '材料成本', amount: 12.1, note: '主材锁价后低于立项预估' },
        { label: '模具成本', amount: 8.4, note: '试模轮次控制在两轮内' },
        { label: '工艺加工', amount: 5.7, note: '量产前工艺参数已稳定' },
        { label: '包装测试', amount: 3.0, note: '包装版本确认后未追加返工' },
        { label: '研发验证', amount: 3.1, note: '红样与小批验证投入' }
      ]
    },
    timeline: [
      {
        nodeKey: 'project-setup',
        nodeName: '产品立项',
        status: 'completed',
        ownerRole: '项目经理 / 管理层',
        actualDate: '2026-05-29',
        summary: '立项说明书、目标机型、成本与风险点已确认。',
        canAdvance: true,
        detailLines: ['产品名称、目标机型、预期工艺已录入。', '供应商比价与开发方式已完成初判。'],
        receiverRole: '项目经理',
        receiverUserName: '张敏',
        receivedAt: '2026-05-20',
        promoterRole: '管理层',
        promoterUserName: '王总',
        promotedAt: '2026-05-29',
        experienceSummary: '完成超队 3.0 立项说明书编制，含目标机型、预期工艺、预估成本和关键风险点。',
        phaseName: '立项阶段',
        documentCount: 3
      },
      {
        nodeKey: 'mold-request',
        nodeName: '申请开模',
        status: 'completed',
        ownerRole: '工程 / 管理层',
        actualDate: '2026-06-02',
        summary: '开模前门禁已达标，进入模具制作。',
        gateLabel: '关键门禁',
        canAdvance: true,
        detailLines: ['结构方案明确。', '关键 BOM、关键工艺路径和包装测试要求已确认。'],
        receiverRole: '工程',
        receiverUserName: '李工',
        receivedAt: '2026-05-30',
        promoterRole: '管理层',
        promoterUserName: '王总',
        promotedAt: '2026-06-02',
        experienceSummary: '结构方案、关键BOM、工艺路径和包装测试要求已通过门禁检查，开模申请获批。',
        phaseName: '开模阶段',
        documentCount: 5
      },
      {
        nodeKey: 'red-sample-test',
        nodeName: '红样测试',
        status: 'current',
        ownerRole: '品质 / 工程',
        plannedDate: '2026-06-11',
        summary: '正在验证跌落、耐磨、酒精与磁吸力等关键指标。',
        nextAction: '补齐红样测试结论，并确认是否进入生产资料整理。',
        riskNote: 'LOGO 区域酒精测试曾出现掉漆，需要复测确认。',
        canAdvance: false,
        detailLines: ['跌落测试已通过。', '酒精测试复测中。', '磁吸力稳定性仍在验证。'],
        receiverRole: '品质',
        receiverUserName: '赵工',
        receivedAt: '2026-06-05',
        promoterRole: '品质 / 工程',
        promoterUserName: '赵工',
        promotedAt: '',
        experienceSummary: '红样注塑件已产出，正在进行跌落、耐磨、酒精、磁吸力四项关键指标验证。',
        phaseName: '样品 / 工艺定型阶段',
        nextReceiverRole: '工程 / 生产',
        nextReceiverUserName: '李工',
        documentCount: 2
      },
      {
        nodeKey: 'sop-freeze',
        nodeName: '整理生产资料',
        status: 'pending',
        ownerRole: '工程 / 生产',
        plannedDate: '2026-06-13',
        summary: '待红样测试通过后冻结 SOP、SIP 和检验标准。',
        canAdvance: false,
        receiverRole: '工程',
        receiverUserName: '--',
        receivedAt: '',
        promoterRole: '工程 / 生产',
        promoterUserName: '--',
        promotedAt: '',
        experienceSummary: '等待红样测试通过后，开始整理注塑SOP、组装SIP、检验标准等生产资料。',
        phaseName: '样品 / 工艺定型阶段',
        nextReceiverRole: '生产',
        nextReceiverUserName: '--',
        documentCount: 0
      },
      {
        nodeKey: 'pilot-run',
        nodeName: '小批量测试',
        status: 'pending',
        ownerRole: '生产 / 项目经理',
        plannedDate: '2026-06-16',
        summary: '验证物料到位、工序节拍和不良率。',
        gateLabel: '产线门禁',
        canAdvance: false,
        receiverRole: '生产',
        receiverUserName: '--',
        receivedAt: '',
        promoterRole: '生产 / 项目经理',
        promoterUserName: '--',
        promotedAt: '',
        experienceSummary: '待生产资料整理完成后，进行小批量产线验证，确认物料到位、节拍和不良率。',
        phaseName: '市场验证阶段',
        nextReceiverRole: '项目经理',
        nextReceiverUserName: '--',
        documentCount: 0
      }
    ],
    bomCompareRows: [
      { versionNo: 'A.1', statusLabel: '已归档', materialCost: 27.8, processCost: 6.3, totalCost: 34.1, delta: 0 },
      { versionNo: 'A.2', statusLabel: '已归档', materialCost: 28.6, processCost: 6.8, totalCost: 35.4, delta: 1.3 },
      { versionNo: 'A.3', statusLabel: '当前', materialCost: 26.9, processCost: 5.4, totalCost: 32.3, delta: -3.1 }
    ],
    bomCostSummary: {
      materialCost: 26.9,
      processCost: 5.4,
      packageCost: 1.4,
      laborCost: 1.8,
      toolingCost: 1.9,
      lossCost: 0.9,
      totalCost: 38.3
    },
    bomItems: [
      { inventoryCode: 'INV-MAT-023', inventoryName: 'TPU 原料 85A', quantity: 1.2, stockUom: 'kg', supplierName: '东莞塑胶 A', unitCost: 25.5, changeType: 'inherit' },
      { inventoryCode: 'INV-MAG-045', inventoryName: 'N52 磁吸组件', quantity: 1, stockUom: 'set', supplierName: '惠州材料 C', unitCost: 3.6, changeType: 'inherit' },
      { inventoryCode: 'INV-PAK-102', inventoryName: '渠道彩盒', quantity: 1, stockUom: 'pcs', supplierName: '深圳包材 D', unitCost: 1.4, changeType: 'replace' }
    ],
    bomItemsByVersion: {
      'A.1': [
        { inventoryCode: 'INV-MAT-023', inventoryName: 'TPU 原料 85A', quantity: 1.2, stockUom: 'kg', supplierName: '东莞塑胶 A', unitCost: 25.5, changeType: 'inherit' },
        { inventoryCode: 'INV-MAG-040', inventoryName: 'N48 磁吸组件', quantity: 1, stockUom: 'set', supplierName: '惠州材料 C', unitCost: 4.1, changeType: 'inherit' },
        { inventoryCode: 'INV-PAK-090', inventoryName: '基础彩盒', quantity: 1, stockUom: 'pcs', supplierName: '深圳包材 D', unitCost: 1.2, changeType: 'inherit' }
      ],
      'A.2': [
        { inventoryCode: 'INV-MAT-023', inventoryName: 'TPU 原料 85A', quantity: 1.2, stockUom: 'kg', supplierName: '东莞塑胶 A', unitCost: 25.5, changeType: 'inherit' },
        { inventoryCode: 'INV-MAG-045', inventoryName: 'N52 磁吸组件', quantity: 1, stockUom: 'set', supplierName: '惠州材料 C', unitCost: 3.6, changeType: 'replace' },
        { inventoryCode: 'INV-PAK-090', inventoryName: '基础彩盒', quantity: 1, stockUom: 'pcs', supplierName: '深圳包材 D', unitCost: 1.2, changeType: 'inherit' }
      ],
      'A.3': [
        { inventoryCode: 'INV-MAT-023', inventoryName: 'TPU 原料 85A', quantity: 1.2, stockUom: 'kg', supplierName: '东莞塑胶 A', unitCost: 25.5, changeType: 'inherit' },
        { inventoryCode: 'INV-MAG-045', inventoryName: 'N52 磁吸组件', quantity: 1, stockUom: 'set', supplierName: '惠州材料 C', unitCost: 3.6, changeType: 'inherit' },
        { inventoryCode: 'INV-PAK-102', inventoryName: '渠道彩盒', quantity: 1, stockUom: 'pcs', supplierName: '深圳包材 D', unitCost: 1.4, changeType: 'replace' }
      ]
    },
    defaultBomVersion: 'A.3',
    toolingSummary: {
      totalCount: 3,
      availableCount: 2,
      trialCount: 1,
      toolingNames: ['超队 3.0 注塑模', '热压治具', '包边治具'],
      targetPath: '/inventories'
    },
    materialCategories: [],
    suppliers: [
      { supplierName: '东莞塑胶 A', role: '主材供应', statusLabel: '已锁价', note: 'TPU 主材供应稳定。' },
      { supplierName: '惠州材料 C', role: '磁吸组件', statusLabel: '待备选', note: '需要补二供风险预案。' },
      { supplierName: '深圳包材 D', role: '彩盒 / 标签', statusLabel: '已确认', note: '渠道包装版本已定稿。' }
    ],
    documents: [
      { fileId: 'f-101-1', fileName: 'PRD-CD30 结构图纸 V3.pdf', category: '工程图纸', versionNo: 'V3', updatedAt: '2026-06-01', owner: '工程部', status: '已冻结', previewUrl: '', downloadUrl: '', stageKey: 'engineering', stageLabel: '工程图纸' },
      { fileId: 'f-101-2', fileName: 'PRD-CD30 红样测试计划.xlsx', category: '测试资料', versionNo: 'A.1', updatedAt: '2026-06-05', owner: '品质部', status: '草稿', previewUrl: '', downloadUrl: '', stageKey: 'testing', stageLabel: '测试资料' },
      { fileId: 'f-101-3', fileName: 'PRD-CD30 注塑 SOP V1.pdf', category: '生产资料', versionNo: 'V1', updatedAt: '2026-06-08', owner: '工程部', status: '已冻结', previewUrl: '', downloadUrl: '', stageKey: 'production', stageLabel: '生产资料' }
    ],
    processRoutes: [
      { sequenceNo: 1, processCode: 'PROC-CD30-IPC-010', processName: '注塑成型', processType: 'operation', inventoryCode: 'INV-MOLD-201', inventoryName: '超队 3.0 注塑模', workstationName: '注塑车间 A01', supplierName: null, qualityRequirement: '外观无缩水、无气泡', outputType: '半成品', summary: 'TPU 原料注塑成型为壳体基材' },
      { sequenceNo: 2, processCode: 'PROC-CD30-TRM-020', processName: '修边去水口', processType: 'operation', inventoryCode: null, inventoryName: null, workstationName: '修边工位 B02', supplierName: null, qualityRequirement: '水口平整，无毛刺', outputType: '半成品', summary: '去除注塑水口和飞边' },
      { sequenceNo: 3, processCode: 'PROC-CD30-SRF-030', processName: '表面处理（喷油）', processType: 'operation', inventoryCode: null, inventoryName: null, workstationName: '喷涂线 C01', supplierName: null, qualityRequirement: '涂层均匀，附着力达标', outputType: '半成品', summary: '壳体表面喷油处理' },
      { sequenceNo: 4, processCode: 'PROC-CD30-MAG-040', processName: '磁铁装配', processType: 'operation', inventoryCode: null, inventoryName: null, workstationName: '装配工位 D01', supplierName: null, qualityRequirement: '磁吸力≥设计值', outputType: '半成品', summary: '将磁吸组件装配到壳体内' },
      { sequenceNo: 5, processCode: 'PROC-CD30-ASM-050', processName: '组件装配', processType: 'operation', inventoryCode: 'INV-JIG-005', inventoryName: '热压治具', workstationName: '装配线 D02', supplierName: null, qualityRequirement: '组件贴合紧密无偏移', outputType: '半成品', summary: '各组件装配确认' },
      { sequenceNo: 6, processCode: 'PROC-CD30-QC-060', processName: '全检外观', processType: 'quality_gate', inventoryCode: null, inventoryName: null, workstationName: '质检区 E01', supplierName: null, qualityRequirement: '外观无瑕疵，颜色一致', outputType: '成品', summary: '成品外观全检' },
      { sequenceNo: 7, processCode: 'PROC-CD30-PKG-070', processName: '包装', processType: 'operation', inventoryCode: null, inventoryName: null, workstationName: '包装线 F01', supplierName: null, qualityRequirement: '标签无误、包装完整', outputType: '成品', summary: '成品包装' }
    ],
    qualityRecords: [
      { testItem: '跌落测试', resultLabel: '通过', owner: '品质部', testedAt: '2026-06-05', note: '边角无裂纹。' },
      { testItem: '酒精测试', resultLabel: '复测中', owner: '品质部', testedAt: '2026-06-08', note: 'LOGO 区域掉漆，已调整喷油参数。' },
      { testItem: '磁吸力测试', resultLabel: '进行中', owner: '工程 / 品质', testedAt: '2026-06-09', note: '验证 N52 方案稳定性。' }
    ]
  },
  102: {
    productId: 102,
    title: '超队 3.0 iPhone18 黑色',
    flowLabel: '新型号线',
    currentNode: '差异测试验证',
    nextNode: '生产资料整理',
    summary: '当前围绕父产品继承边界管理新型号差异，重点处理孔位、黑色色母、改模和差异测试结果。',
    costPanel: {
      showEstimated: false,
      actualTotal: 12.3,
      actualLines: [
        { label: '改模成本', amount: 4.2, note: 'iPhone18 孔位与摄像头位置修模。' },
        { label: '差异材料', amount: 3.6, note: '黑色色母与差异标签。' },
        { label: '差异工艺', amount: 2.1, note: '注塑参数调整与试产确认。' },
        { label: '差异测试', amount: 1.4, note: '孔位匹配、按键手感、外观验证。' },
        { label: '资料整理', amount: 1.0, note: 'SIP / SOP 增量修改。' }
      ]
    },
    timeline: [
      {
        nodeKey: 'variant-setup',
        nodeName: '新型号需求确认',
        status: 'completed',
        ownerRole: '项目经理',
        actualDate: '2026-06-02',
        summary: '确认需求来源为客户新增 iPhone18 黑色版本。',
        canAdvance: true,
        detailLines: ['无需完整立项说明书。', '工艺、BOM 与测试框架默认继承父产品。'],
        receiverRole: '项目经理',
        receiverUserName: '张敏',
        receivedAt: '2026-06-01',
        promoterRole: '项目经理',
        promoterUserName: '张敏',
        promotedAt: '2026-06-02',
        experienceSummary: '北美渠道A确认新增iPhone18黑色版需求，项目经理完成需求登记。',
        phaseName: '扩展确认阶段',
        documentCount: 1
      },
      {
        nodeKey: 'sub-product',
        nodeName: '子版本建立',
        status: 'completed',
        ownerRole: '工程',
        actualDate: '2026-06-03',
        summary: '已在超队 3.0 下创建子 Product，版本从 A 开始。',
        gateLabel: '扩展入口',
        canAdvance: true,
        receiverRole: '工程',
        receiverUserName: '李工',
        receivedAt: '2026-06-02',
        promoterRole: '工程',
        promoterUserName: '李工',
        promotedAt: '2026-06-03',
        experienceSummary: '在超队3.0下创建子Product，工艺、BOM和测试框架默认继承父产品。',
        phaseName: '扩展确认阶段',
        documentCount: 2
      },
      {
        nodeKey: 'mold-branch',
        nodeName: '改模申请',
        status: 'completed',
        ownerRole: '模具工程师',
        actualDate: '2026-06-04',
        summary: '确认走改模分支，不需要新开整套模具。',
        gateLabel: '模具分支',
        canAdvance: true,
        detailLines: ['已有模具增加 iPhone18 穴位。', '周期短于全新开模。'],
        receiverRole: '工程',
        receiverUserName: '李工',
        receivedAt: '2026-06-03',
        promoterRole: '模具工程师',
        promoterUserName: '陈工',
        promotedAt: '2026-06-04',
        experienceSummary: '对比开模/改模两种方案后确认改模，已有模具增加iPhone18穴位，周期更短。',
        phaseName: '模具决策阶段',
        documentCount: 3
      },
      {
        nodeKey: 'variant-test',
        nodeName: '差异测试验证',
        status: 'current',
        ownerRole: '品质 / 工程',
        plannedDate: '2026-06-10',
        summary: '当前只验证变化部分，不跑完整测试套件。',
        nextAction: '补齐磁吸力与按键手感测试，确认是否可进入资料整理。',
        riskNote: '磁吸力仍偏弱，需要继续验证色母和结构公差影响。',
        canAdvance: false,
        detailLines: ['孔位匹配已通过。', '外观确认已通过。', '磁吸力测试未通过。'],
        receiverRole: '品质',
        receiverUserName: '赵工',
        receivedAt: '2026-06-06',
        promoterRole: '品质 / 工程',
        promoterUserName: '赵工',
        promotedAt: '',
        experienceSummary: '只验证变化部分：孔位匹配、按键手感、外观确认、磁吸力。磁吸力暂未达标。',
        phaseName: '验证阶段',
        nextReceiverRole: '工程 / 生产',
        nextReceiverUserName: '李工',
        documentCount: 1
      },
      {
        nodeKey: 'variant-docs',
        nodeName: '生产资料整理',
        status: 'pending',
        ownerRole: '工程 / 生产',
        plannedDate: '2026-06-12',
        summary: '基于父产品 SIP / SOP 做增量修改。',
        canAdvance: false,
        receiverRole: '工程',
        receiverUserName: '--',
        receivedAt: '',
        promoterRole: '工程 / 生产',
        promoterUserName: '--',
        promotedAt: '',
        experienceSummary: '在父产品SIP/SOP基础上增量修改差异部分，不重复编制完整生产资料。',
        phaseName: '验证阶段',
        nextReceiverRole: '品质主管',
        nextReceiverUserName: '--',
        documentCount: 0
      },
      {
        nodeKey: 'variant-freeze',
        nodeName: '版本冻结',
        status: 'pending',
        ownerRole: '品质主管 / 管理层',
        plannedDate: '2026-06-14',
        summary: '锁定该型号 BOM、工艺和差异图纸。',
        gateLabel: '冻结门禁',
        canAdvance: false,
        receiverRole: '品质主管',
        receiverUserName: '--',
        receivedAt: '',
        promoterRole: '管理层',
        promoterUserName: '--',
        promotedAt: '',
        experienceSummary: '差异测试通过后冻结该型号BOM、工艺和差异图纸，形成正式子版本。',
        phaseName: '投产发布阶段',
        nextReceiverRole: '管理层',
        nextReceiverUserName: '--',
        documentCount: 0
      }
    ],
    bomCompareRows: [
      { versionNo: 'A.1', statusLabel: '已归档', materialCost: 8.9, processCost: 3.1, totalCost: 12.0, delta: 0 },
      { versionNo: 'A.2', statusLabel: '当前', materialCost: 9.2, processCost: 3.1, totalCost: 12.3, delta: 0.3 }
    ],
    bomCostSummary: {
      materialCost: 9.2,
      processCost: 3.1,
      packageCost: 0.6,
      laborCost: 0.9,
      toolingCost: 1.4,
      lossCost: 0.2,
      totalCost: 15.4
    },
    bomItems: [
      { inventoryCode: 'INV-MAT-067', inventoryName: '黑色色母', quantity: 0.1, stockUom: 'kg', supplierName: '东莞塑胶 A', unitCost: 18.2, changeType: 'new' },
      { inventoryCode: 'INV-ACC-118', inventoryName: 'iPhone18 孔位治具', quantity: 1, stockUom: 'set', supplierName: '东莞模具 C', unitCost: 1.8, changeType: 'new' },
      { inventoryCode: 'INV-PAK-156', inventoryName: '黑色标签贴纸', quantity: 1, stockUom: 'pcs', supplierName: '深圳包材 D', unitCost: 0.6, changeType: 'replace' }
    ],
    bomItemsByVersion: {
      'A.1': [
        { inventoryCode: 'INV-MAT-023', inventoryName: 'TPU 原料 85A', quantity: 1.2, stockUom: 'kg', supplierName: '东莞塑胶 A', unitCost: 25.5, changeType: 'inherit' },
        { inventoryCode: 'INV-MAG-045', inventoryName: 'N52 磁吸组件', quantity: 1, stockUom: 'set', supplierName: '惠州材料 C', unitCost: 3.6, changeType: 'inherit' },
        { inventoryCode: 'INV-PAK-118', inventoryName: '标签贴纸', quantity: 1, stockUom: 'pcs', supplierName: '深圳包材 D', unitCost: 0.5, changeType: 'inherit' }
      ],
      'A.2': [
        { inventoryCode: 'INV-MAT-067', inventoryName: '黑色色母', quantity: 0.1, stockUom: 'kg', supplierName: '东莞塑胶 A', unitCost: 18.2, changeType: 'new' },
        { inventoryCode: 'INV-MAG-045', inventoryName: 'N52 磁吸组件', quantity: 1, stockUom: 'set', supplierName: '惠州材料 C', unitCost: 3.6, changeType: 'inherit' },
        { inventoryCode: 'INV-ACC-118', inventoryName: 'iPhone18 孔位治具', quantity: 1, stockUom: 'set', supplierName: '东莞模具 C', unitCost: 1.8, changeType: 'new' },
        { inventoryCode: 'INV-PAK-156', inventoryName: '黑色标签贴纸', quantity: 1, stockUom: 'pcs', supplierName: '深圳包材 D', unitCost: 0.6, changeType: 'replace' }
      ]
    },
    defaultBomVersion: 'A.2',
    toolingSummary: {
      totalCount: 1,
      availableCount: 0,
      trialCount: 1,
      toolingNames: ['iPhone18 改模注塑模'],
      targetPath: '/inventories'
    },
    materialCategories: [],
    suppliers: [
      { supplierName: '东莞塑胶 A', role: '色母 / TPU', statusLabel: '待确认', note: '黑色色母报价已回复，待补批次验证。' },
      { supplierName: '东莞模具 C', role: '改模 / 治具', statusLabel: '进行中', note: '差异孔位改模中。' },
      { supplierName: '深圳包材 D', role: '标签贴纸', statusLabel: '已确认', note: '渠道差异标签已定稿。' }
    ],
    documents: [
      { fileId: 'f-102-1', fileName: 'PRD-CD30-IP18 孔位差异图.pdf', category: '差异图纸', versionNo: 'A.2', updatedAt: '2026-06-03', owner: '工程部', status: '已冻结', previewUrl: '', downloadUrl: '', stageKey: 'variant', stageLabel: '差异资料' },
      { fileId: 'f-102-2', fileName: 'PRD-CD30-IP18 黑色外观确认.pdf', category: '客户确认件', versionNo: 'A.1', updatedAt: '2026-06-06', owner: '销售部', status: '已冻结', previewUrl: '', downloadUrl: '', stageKey: 'customer_confirm', stageLabel: '客户确认件' },
      { fileId: 'f-102-3', fileName: 'PRD-CD30-IP18 差异测试记录.xlsx', category: '测试资料', versionNo: 'A.1', updatedAt: '2026-06-09', owner: '品质部', status: '草稿', previewUrl: '', downloadUrl: '', stageKey: 'testing', stageLabel: '测试资料' },
      { fileId: 'f-102-4', fileName: 'PRD-CD30-IP18 增量 SIP V1.pdf', category: '生产资料', versionNo: 'V1', updatedAt: '2026-06-10', owner: '工程部', status: '草稿', previewUrl: '', downloadUrl: '', stageKey: 'production', stageLabel: '生产资料' }
    ],
    processRoutes: [
      { sequenceNo: 1, processCode: 'PROC-CD30-IPC-010', processName: '注塑成型（改模）', processType: 'operation', inventoryCode: 'INV-MOLD-218', inventoryName: 'iPhone18 改模注塑模', workstationName: '注塑车间 A01', supplierName: null, qualityRequirement: '孔位匹配准确', outputType: '半成品', summary: '基于改模后的注塑模成型' },
      { sequenceNo: 2, processCode: 'PROC-CD30-TRM-020', processName: '修边去水口', processType: 'operation', inventoryCode: null, inventoryName: null, workstationName: '修边工位 B02', supplierName: null, qualityRequirement: '水口平整无毛刺', outputType: '半成品', summary: '差异工序与父产品一致' },
      { sequenceNo: 3, processCode: 'PROC-CD30-SRF-031', processName: '表面处理（黑色）', processType: 'operation', inventoryCode: null, inventoryName: null, workstationName: '喷涂线 C01', supplierName: null, qualityRequirement: '黑色涂层均匀无偏色', outputType: '半成品', summary: '采用黑色色母，颜色差异工序' },
      { sequenceNo: 4, processCode: 'PROC-CD30-MAG-040', processName: '磁铁装配', processType: 'operation', inventoryCode: null, inventoryName: null, workstationName: '装配工位 D01', supplierName: null, qualityRequirement: '磁吸力≥设计值', outputType: '半成品', summary: '差异工序与父产品一致' },
      { sequenceNo: 5, processCode: 'PROC-CD30-QC-060', processName: '全检外观', processType: 'quality_gate', inventoryCode: null, inventoryName: null, workstationName: '质检区 E01', supplierName: null, qualityRequirement: '黑色外观无瑕疵', outputType: '成品', summary: '差异工序：黑色外观检查' }
    ],
    qualityRecords: [
      { testItem: '孔位匹配', resultLabel: '通过', owner: '工程部', testedAt: '2026-06-08', note: '按键与摄像头位置正常。' },
      { testItem: '外观确认', resultLabel: '通过', owner: '项目部', testedAt: '2026-06-08', note: '黑色外观已确认。' },
      { testItem: '磁吸力', resultLabel: '不通过', owner: '品质部', testedAt: '2026-06-09', note: '吸力偏弱，需要继续验证。' }
    ]
  },
  104: {
    productId: 104,
    title: '亮甲 3.0 镜面手机壳',
    flowLabel: '新产品线',
    currentNode: '正式发布',
    nextNode: '版本追溯',
    summary: '该产品线已发布，当前页面主要用于回溯版本、资料冻结结果和供应商复用情况。',
    costPanel: {
      showEstimated: true,
      estimatedTotal: 36.2,
      estimatedLines: [
        { label: '材料成本', amount: 13.4, note: '镜面片、TPU 主材与装饰件。' },
        { label: '模具成本', amount: 8.8, note: '贴合相关治具与模具。' },
        { label: '工艺加工', amount: 7.3, note: '镜面贴合、注塑与外观处理。' },
        { label: '包装测试', amount: 3.1, note: '零售包装与渠道测试。' },
        { label: '损耗预估', amount: 3.6, note: '试产损耗与备料波动。' }
      ],
      actualTotal: 33.5,
      actualLines: [
        { label: '材料成本', amount: 12.9, note: '镜面片采购价格低于预估。' },
        { label: '模具成本', amount: 7.9, note: '模具稳定后返修成本下降。' },
        { label: '工艺加工', amount: 6.7, note: '贴合良率高于目标。' },
        { label: '包装测试', amount: 2.9, note: '零售包装一次通过。' },
        { label: '验证投入', amount: 3.1, note: '量产前验证收口。' }
      ]
    },
    timeline: [
      {
        nodeKey: 'setup',
        nodeName: '产品立项',
        status: 'completed',
        ownerRole: '项目经理 / 管理层',
        actualDate: '2026-04-18',
        summary: '镜面产品线已通过立项。',
        canAdvance: true,
        receiverRole: '项目经理',
        receiverUserName: '刘浩',
        receivedAt: '2026-04-10',
        promoterRole: '管理层',
        promoterUserName: '王总',
        promotedAt: '2026-04-18',
        experienceSummary: '完成亮甲3.0镜面产品线立项，含镜面片工艺评估、贴合方案和零售包装方向。',
        phaseName: '立项阶段',
        documentCount: 4
      },
      {
        nodeKey: 'sample-signoff',
        nodeName: '签样确认',
        status: 'completed',
        ownerRole: '项目经理 / 客户',
        actualDate: '2026-05-06',
        summary: '产品外观和样品版本已冻结。',
        gateLabel: '重要门禁',
        canAdvance: true,
        receiverRole: '项目经理',
        receiverUserName: '刘浩',
        receivedAt: '2026-05-01',
        promoterRole: '客户',
        promoterUserName: '日本零售客户',
        promotedAt: '2026-05-06',
        experienceSummary: '客户确认外观和样品版本，签样后冻结样品资料。',
        phaseName: '样品 / 工艺定型阶段',
        documentCount: 3
      },
      {
        nodeKey: 'mx-pilot',
        nodeName: 'MX 小批量测试',
        status: 'completed',
        ownerRole: '生产 / 项目经理',
        actualDate: '2026-05-28',
        summary: '墨西哥端小批量验证已跑通。',
        canAdvance: true,
        receiverRole: '生产',
        receiverUserName: '孙工',
        receivedAt: '2026-05-20',
        promoterRole: '项目经理',
        promoterUserName: '刘浩',
        promotedAt: '2026-05-28',
        experienceSummary: '墨西哥端产线小批量验证跑通，品质和产能确认可承接量产。',
        phaseName: '市场验证阶段',
        documentCount: 2
      },
      {
        nodeKey: 'release',
        nodeName: '正式发布',
        status: 'current',
        ownerRole: '管理层',
        actualDate: '2026-05-29',
        summary: '当前已正式发布，详情页用于回溯版本和资料。',
        nextAction: '根据历史版本与资料冻结记录，支持后续型号扩展复用。',
        canAdvance: true,
        receiverRole: '管理层',
        receiverUserName: '王总',
        receivedAt: '2026-05-28',
        promoterRole: '管理层',
        promoterUserName: '王总',
        promotedAt: '2026-05-29',
        experienceSummary: '所有验证通过后正式发布亮甲3.0镜面产品线，BOM/工艺/包装资料已冻结。',
        phaseName: '投产发布阶段',
        documentCount: 5
      }
    ],
    bomCompareRows: [
      { versionNo: 'A.4', statusLabel: '已归档', materialCost: 28.8, processCost: 6.0, totalCost: 34.8, delta: 0 },
      { versionNo: 'B.1', statusLabel: '当前', materialCost: 27.4, processCost: 6.1, totalCost: 33.5, delta: -1.3 }
    ],
    bomCostSummary: {
      materialCost: 27.4,
      processCost: 6.1,
      packageCost: 1.9,
      laborCost: 1.6,
      toolingCost: 2.3,
      lossCost: 0.8,
      totalCost: 40.1
    },
    bomItems: [
      { inventoryCode: 'INV-MAT-081', inventoryName: '镜面片', quantity: 1, stockUom: 'pcs', supplierName: '深圳板材 B', unitCost: 6.8, changeType: 'inherit' },
      { inventoryCode: 'INV-MAT-024', inventoryName: 'TPU 原料 90A', quantity: 1.1, stockUom: 'kg', supplierName: '东莞塑胶 A', unitCost: 24.6, changeType: 'inherit' },
      { inventoryCode: 'INV-PAK-188', inventoryName: '零售吊卡包装', quantity: 1, stockUom: 'pcs', supplierName: '深圳包材 D', unitCost: 1.9, changeType: 'replace' }
    ],
    bomItemsByVersion: {
      'A.4': [
        { inventoryCode: 'INV-MAT-081', inventoryName: '镜面片', quantity: 1, stockUom: 'pcs', supplierName: '深圳板材 B', unitCost: 7.1, changeType: 'inherit' },
        { inventoryCode: 'INV-MAT-024', inventoryName: 'TPU 原料 90A', quantity: 1.1, stockUom: 'kg', supplierName: '东莞塑胶 A', unitCost: 24.6, changeType: 'inherit' },
        { inventoryCode: 'INV-PAK-166', inventoryName: '标准包装', quantity: 1, stockUom: 'pcs', supplierName: '深圳包材 D', unitCost: 1.7, changeType: 'inherit' }
      ],
      'B.1': [
        { inventoryCode: 'INV-MAT-081', inventoryName: '镜面片', quantity: 1, stockUom: 'pcs', supplierName: '深圳板材 B', unitCost: 6.8, changeType: 'replace' },
        { inventoryCode: 'INV-MAT-024', inventoryName: 'TPU 原料 90A', quantity: 1.1, stockUom: 'kg', supplierName: '东莞塑胶 A', unitCost: 24.6, changeType: 'inherit' },
        { inventoryCode: 'INV-PAK-188', inventoryName: '零售吊卡包装', quantity: 1, stockUom: 'pcs', supplierName: '深圳包材 D', unitCost: 1.9, changeType: 'replace' }
      ]
    },
    defaultBomVersion: 'B.1',
    toolingSummary: {
      totalCount: 2,
      availableCount: 2,
      trialCount: 0,
      toolingNames: ['亮甲 3.0 注塑模', '镜面贴合治具'],
      targetPath: '/inventories'
    },
    materialCategories: [],
    suppliers: [
      { supplierName: '深圳板材 B', role: '镜面外观件', statusLabel: '稳定合作', note: '镜面片已转量产供应。' },
      { supplierName: '东莞塑胶 A', role: 'TPU 主材', statusLabel: '稳定合作', note: '月结 45 天。' },
      { supplierName: '深圳包材 D', role: '零售包装', statusLabel: '已冻结', note: '包装版本可直接复用。' }
    ],
    documents: [
      { fileId: 'f-104-1', fileName: 'PRD-LJ30 外观确认稿 V2.pdf', category: '设计稿件', versionNo: 'V2', updatedAt: '2026-05-10', owner: '设计部', status: '已冻结', previewUrl: '', downloadUrl: '', stageKey: 'engineering', stageLabel: '工程图纸' },
      { fileId: 'f-104-2', fileName: 'PRD-LJ30 包装结构图 V3.pdf', category: '包装资料', versionNo: 'V3', updatedAt: '2026-05-21', owner: '设计部', status: '已冻结', previewUrl: '', downloadUrl: '', stageKey: 'packaging', stageLabel: '包装资料' },
      { fileId: 'f-104-3', fileName: 'PRD-LJ30 黄样确认记录.pdf', category: '样品资料', versionNo: 'B.1', updatedAt: '2026-05-25', owner: '项目部', status: '已归档', previewUrl: '', downloadUrl: '', stageKey: 'sample', stageLabel: '样品资料' },
      { fileId: 'f-104-4', fileName: 'PRD-LJ30 镜面贴合 SOP V2.pdf', category: '生产资料', versionNo: 'V2', updatedAt: '2026-05-22', owner: '工程部', status: '已冻结', previewUrl: '', downloadUrl: '', stageKey: 'production', stageLabel: '生产资料' }
    ],
    processRoutes: [
      { sequenceNo: 1, processCode: 'PROC-LJ30-IPC-010', processName: '注塑成型', processType: 'operation', inventoryCode: 'INV-MOLD-233', inventoryName: '亮甲 3.0 注塑模', workstationName: '注塑车间 A02', supplierName: null, qualityRequirement: '外观无缩水无气泡', outputType: '半成品', summary: 'TPU 原料注塑成型' },
      { sequenceNo: 2, processCode: 'PROC-LJ30-MIR-020', processName: '镜面贴合', processType: 'operation', inventoryCode: 'INV-JIG-011', inventoryName: '镜面贴合治具', workstationName: '贴合车间 G01', supplierName: null, qualityRequirement: '贴合无气泡无偏移', outputType: '半成品', summary: '镜面片与壳体热压贴合' },
      { sequenceNo: 3, processCode: 'PROC-LJ30-SRF-030', processName: '表面处理', processType: 'operation', inventoryCode: null, inventoryName: null, workstationName: '喷涂线 C02', supplierName: null, qualityRequirement: '涂层均匀附着力达标', outputType: '半成品', summary: '壳体表面处理' },
      { sequenceNo: 4, processCode: 'PROC-LJ30-QC-040', processName: '全检外观', processType: 'quality_gate', inventoryCode: null, inventoryName: null, workstationName: '质检区 E02', supplierName: null, qualityRequirement: '镜面无划痕无偏色', outputType: '成品', summary: '镜面产品外观全检' },
      { sequenceNo: 5, processCode: 'PROC-LJ30-PKG-050', processName: '零售包装', processType: 'operation', inventoryCode: null, inventoryName: null, workstationName: '包装线 F02', supplierName: null, qualityRequirement: '吊卡包装完整标签无误', outputType: '成品', summary: '零售吊卡包装' }
    ],
    qualityRecords: [
      { testItem: '百格测试', resultLabel: '通过', owner: '品质部', testedAt: '2026-05-21', note: '镜面层附着力合格。' },
      { testItem: '跌落测试', resultLabel: '通过', owner: '品质部', testedAt: '2026-05-20', note: '边框无开裂。' },
      { testItem: 'MX 小批验证', resultLabel: '通过', owner: '项目部', testedAt: '2026-05-28', note: '墨西哥端产线已跑通。' }
    ]
  }
}

const fileSections: FileSection[] = [
  {
    key: 'product_files',
    title: '产品文件',
    description: '新产品线图纸、SOP、测试计划和量产资料按产品线归档。',
    groups: [
      {
        groupId: 'product-101',
        projectName: '超队 3.0',
        productCode: 'PRD-CD30-001',
        productId: 101,
        owner: '张敏',
        updatedAt: '2026-06-08',
        productType: 'product',
        files: [
          { fileId: 'f-101-1', fileName: 'PRD-CD30 结构图纸 V3.pdf', category: '工程图纸', owner: '工程部', uploadedAt: '2026-06-01', versionNo: 'V3', productId: 101, stageKey: 'engineering', stageLabel: '工程图纸' },
          { fileId: 'f-101-2', fileName: 'PRD-CD30 红样测试计划.xlsx', category: '测试资料', owner: '品质部', uploadedAt: '2026-06-05', versionNo: 'A.1', productId: 101, stageKey: 'testing', stageLabel: '测试资料' },
          { fileId: 'f-101-3', fileName: 'PRD-CD30 注塑 SOP V1.pdf', category: '生产资料', owner: '工程部', uploadedAt: '2026-06-08', versionNo: 'V1', productId: 101, stageKey: 'production', stageLabel: '生产资料' }
        ]
      }
    ]
  },
  {
    key: 'variant_files',
    title: '新型号文件',
    description: '新型号线只保留差异图纸、差异 BOM、客户确认件和差异测试记录。',
    groups: [
      {
        groupId: 'variant-102',
        projectName: '超队 3.0 iPhone18 黑色',
        productCode: 'PRD-CD30-IP18-BLK',
        productId: 102,
        owner: '刘浩',
        updatedAt: '2026-06-09',
        productType: 'variant',
        files: [
          { fileId: 'f-102-1', fileName: 'PRD-CD30-IP18 孔位差异图.pdf', category: '差异图纸', owner: '工程部', uploadedAt: '2026-06-03', versionNo: 'A.2', productId: 102, stageKey: 'variant', stageLabel: '差异资料' },
          { fileId: 'f-102-2', fileName: 'PRD-CD30-IP18 黑色外观确认.pdf', category: '客户确认件', owner: '销售部', uploadedAt: '2026-06-06', versionNo: 'A.1', productId: 102, stageKey: 'customer_confirm', stageLabel: '客户确认件' },
          { fileId: 'f-102-3', fileName: 'PRD-CD30-IP18 差异测试记录.xlsx', category: '测试资料', owner: '品质部', uploadedAt: '2026-06-09', versionNo: 'A.1', productId: 102, stageKey: 'testing', stageLabel: '测试资料' }
        ]
      }
    ]
  }
]

const testCategories: TestCategoryItem[] = [
  { categoryId: 'drop', categoryName: '跌落测试', method: '1.2m 六面各两次', defaultFrequency: '红样', owner: '品质部' },
  { categoryId: 'wear', categoryName: '耐磨测试', method: '表面往复摩擦 1000 次', defaultFrequency: '黄样', owner: '品质部' },
  { categoryId: 'alcohol', categoryName: '酒精测试', method: '95% 酒精 500 次', defaultFrequency: '红样', owner: '品质部' },
  { categoryId: 'magnetic', categoryName: '磁吸力测试', method: '标准治具吸附验证', defaultFrequency: '黄样', owner: '工程 / 品质' }
]

const testRecords: TestRecordItem[] = [
  { recordId: 'tr-001', productId: 101, productName: '超队 3.0 磁吸手机壳', testCategory: '跌落测试', result: '通过', owner: '品质部', testedAt: '2026-06-05', note: '边角无裂纹。' },
  { recordId: 'tr-002', productId: 101, productName: '超队 3.0 磁吸手机壳', testCategory: '酒精测试', result: '复测中', owner: '品质部', testedAt: '2026-06-08', note: 'LOGO 区域掉漆，已调整参数。' },
  { recordId: 'tr-003', productId: 102, productName: '超队 3.0 iPhone18 黑色', testCategory: '孔位匹配', result: '通过', owner: '工程部', testedAt: '2026-06-08', note: '按键与摄像头位置正常。' }
]

const inventoryTree: InventoryTreeNode[] = [
  {
    nodeId: 'semi-finished',
    label: '半成品组',
    nodeType: 'category',
    count: 2,
    children: [
      {
        nodeId: 'semi-product-cd30',
        label: 'NHC 超队 3.0',
        nodeType: 'product',
        groupCode: 'NHC',
        count: 2,
        children: [
          {
            nodeId: 'semi-group-cd30-inkjet',
            label: 'NHC01 超队 3.0 喷墨',
            nodeType: 'product-group',
            groupCode: 'NHC01',
            count: 1,
            children: [
              {
                nodeId: 'semi-model-cd30-inkjet-ip18',
                label: 'NHC011111 超队 3.0 喷墨 iPhone18',
                nodeType: 'product-model',
                groupCode: 'NHC011111',
                count: 1
              }
            ]
          }
        ]
      }
    ]
  },
  {
    nodeId: 'raw',
    label: '原材料',
    nodeType: 'category',
    count: 4,
    children: [
      { nodeId: 'raw-tpu', label: 'TPU', nodeType: 'category', count: 2 },
      { nodeId: 'raw-pc', label: 'PC', nodeType: 'category', count: 1 },
      { nodeId: 'raw-color', label: '色母', nodeType: 'category', count: 1 }
    ]
  },
  {
    nodeId: 'component',
    label: '功能件',
    nodeType: 'category',
    count: 3,
    children: [
      { nodeId: 'component-magnet', label: '磁吸组件', nodeType: 'category', count: 1 },
      { nodeId: 'component-deco', label: '装饰件', nodeType: 'category', count: 1 },
      { nodeId: 'component-functional', label: '结构辅件', nodeType: 'category', count: 1 }
    ]
  },
  {
    nodeId: 'package',
    label: '包材',
    nodeType: 'category',
    count: 3,
    children: [
      { nodeId: 'package-box', label: '彩盒', nodeType: 'category', count: 1 },
      { nodeId: 'package-inlay', label: '内托', nodeType: 'category', count: 1 },
      { nodeId: 'package-label', label: '标签', nodeType: 'category', count: 1 }
    ]
  },
  {
    nodeId: 'tooling',
    label: '模具治具',
    nodeType: 'category',
    count: 6,
    children: [
      {
        nodeId: 'tooling-product-cd30',
        label: 'MHC 超队 3.0',
        nodeType: 'product',
        groupCode: 'MHC',
        count: 4,
        children: [
          {
            nodeId: 'tooling-group-cd30-mold',
            label: 'MHC01 超队 3.0 注塑模',
            nodeType: 'tooling-group',
            groupCode: 'MHC01',
            count: 2,
            children: [
              {
                nodeId: 'tooling-leaf-cd30-ip18-mold',
                label: 'MHC011111 超队 3.0 iPhone18 注塑模',
                nodeType: 'tooling-leaf',
                groupCode: 'MHC011111',
                count: 1
              }
            ]
          },
          {
            nodeId: 'tooling-group-cd30-hotpress',
            label: 'MHC02 超队 3.0 热压治具',
            nodeType: 'tooling-group',
            groupCode: 'MHC02',
            count: 1
          },
          {
            nodeId: 'tooling-group-cd30-edge',
            label: 'MHC03 超队 3.0 包边治具',
            nodeType: 'tooling-group',
            groupCode: 'MHC03',
            count: 1
          }
        ]
      },
      {
        nodeId: 'tooling-product-lj30',
        label: 'MHC 亮甲 3.0',
        nodeType: 'product',
        groupCode: 'MHC',
        count: 2,
        children: [
          {
            nodeId: 'tooling-group-lj30-mold',
            label: 'MHC04 亮甲 3.0 注塑模',
            nodeType: 'tooling-group',
            groupCode: 'MHC04',
            count: 1
          },
          {
            nodeId: 'tooling-group-lj30-mirror',
            label: 'MHC05 亮甲 3.0 镜面贴合治具',
            nodeType: 'tooling-group',
            groupCode: 'MHC05',
            count: 1
          }
        ]
      }
    ]
  }
]

const inventoryItems: InventoryListRow[] = [
  { itemId: 'inv-020', nodeId: 'semi-model-cd30-inkjet-ip18', code: 'INV-SEMI-118', name: '超队 3.0 半成品', spec: '喷墨', stock: '86pcs', inventoryType: '半成品', productName: '超队 3.0', phoneModel: 'iPhone18', status: 'reserved', supplierName: '内部半成品组', updatedAt: '2026-06-09' },
  { itemId: 'inv-001', nodeId: 'raw-tpu', code: 'INV-MAT-023', name: 'TPU 原料 85A', spec: '25kg / 包', stock: '500kg', inventoryType: '原材料', status: 'available', supplierName: '东莞塑胶 A', updatedAt: '2026-06-08' },
  { itemId: 'inv-002', nodeId: 'raw-tpu', code: 'INV-MAT-024', name: 'TPU 原料 90A', spec: '25kg / 包', stock: '280kg', inventoryType: '原材料', status: 'reserved', supplierName: '东莞塑胶 A', updatedAt: '2026-06-07' },
  { itemId: 'inv-003', nodeId: 'raw-pc', code: 'INV-MAT-045', name: 'PC 背板', spec: '0.8mm', stock: '320pcs', inventoryType: '原材料', status: 'reserved', supplierName: '深圳板材 B', updatedAt: '2026-06-07' },
  { itemId: 'inv-004', nodeId: 'raw-color', code: 'INV-MAT-067', name: '黑色色母', spec: '5kg / 箱', stock: '20kg', inventoryType: '原材料', status: 'available', supplierName: '东莞塑胶 A', updatedAt: '2026-06-09' },
  { itemId: 'inv-005', nodeId: 'component-magnet', code: 'INV-MAG-045', name: 'N52 磁吸组件', spec: '1 set', stock: '200set', inventoryType: '功能件', status: 'reserved', supplierName: '惠州材料 C', updatedAt: '2026-06-08' },
  { itemId: 'inv-006', nodeId: 'component-deco', code: 'INV-DEC-010', name: '装饰环', spec: '黑钛色', stock: '1200pcs', inventoryType: '功能件', status: 'available', supplierName: '深圳五金 E', updatedAt: '2026-06-06' },
  { itemId: 'inv-007', nodeId: 'component-functional', code: 'INV-ACC-118', name: 'iPhone18 孔位治具', spec: '1 set', stock: '2set', inventoryType: '功能件', status: 'in_use', supplierName: '东莞模具 C', updatedAt: '2026-06-09' },
  { itemId: 'inv-008', nodeId: 'package-box', code: 'INV-PAK-102', name: '渠道彩盒', spec: '单盒', stock: '3000pcs', inventoryType: '包材', status: 'available', supplierName: '深圳包材 D', updatedAt: '2026-06-05' },
  { itemId: 'inv-009', nodeId: 'package-inlay', code: 'INV-PAK-166', name: '标准内托', spec: '单套', stock: '1800pcs', inventoryType: '包材', status: 'available', supplierName: '深圳包材 D', updatedAt: '2026-06-03' },
  { itemId: 'inv-010', nodeId: 'package-label', code: 'INV-PAK-156', name: '黑色标签贴纸', spec: '单枚', stock: '5000pcs', inventoryType: '包材', status: 'available', supplierName: '深圳包材 D', updatedAt: '2026-06-09' },
  { itemId: 'inv-011', nodeId: 'tooling-group-cd30-mold', code: 'INV-MOLD-201', name: '超队 3.0 注塑模', spec: '1 套', stock: '1 套', inventoryType: '模具', productName: '超队 3.0', phoneModel: '', status: 'in_use', supplierName: '东莞模具 C', updatedAt: '2026-06-04' },
  { itemId: 'inv-012', nodeId: 'tooling-group-cd30-hotpress', code: 'INV-JIG-005', name: '热压治具', spec: '1 套', stock: '1 套', inventoryType: '治具', productName: '超队 3.0', phoneModel: '', status: 'available', supplierName: '东莞模具 C', updatedAt: '2026-06-04' },
  { itemId: 'inv-013', nodeId: 'tooling-group-cd30-edge', code: 'INV-JIG-008', name: '包边治具', spec: '1 套', stock: '1 套', inventoryType: '治具', productName: '超队 3.0', phoneModel: '', status: 'available', supplierName: '东莞模具 C', updatedAt: '2026-06-06' },
  { itemId: 'inv-014', nodeId: 'tooling-leaf-cd30-ip18-mold', code: 'INV-MOLD-218', name: 'iPhone18 改模注塑模', spec: '1 套', stock: '1 套', inventoryType: '模具', productName: '超队 3.0', phoneModel: 'iPhone18', status: 'in_use', supplierName: '东莞模具 C', updatedAt: '2026-06-09' },
  { itemId: 'inv-015', nodeId: 'tooling-group-lj30-mold', code: 'INV-MOLD-233', name: '亮甲 3.0 注塑模', spec: '1 套', stock: '1 套', inventoryType: '模具', productName: '亮甲 3.0', phoneModel: '', status: 'available', supplierName: '东莞模具 C', updatedAt: '2026-05-26' },
  { itemId: 'inv-016', nodeId: 'tooling-group-lj30-mirror', code: 'INV-JIG-011', name: '镜面贴合治具', spec: '1 套', stock: '1 套', inventoryType: '治具', productName: '亮甲 3.0', phoneModel: '', status: 'available', supplierName: '东莞模具 C', updatedAt: '2026-05-27' }
]

const bomCenterRows: BomCenterRow[] = [
  {
    productId: 101,
    productCode: 'PRD-CD30-001',
    productName: '超队 3.0 磁吸手机壳',
    bomType: 'EBOM',
    currentVersion: 'A.3',
    status: 'developing',
    materialCost: 26.9,
    processCost: 5.4,
    totalCost: 32.3,
    supplierNote: '磁吸组件已锁主供，替代料待备选。',
    updatedAt: '2026-06-08'
  },
  {
    productId: 102,
    productCode: 'PRD-CD30-IP18-BLK',
    productName: '超队 3.0 iPhone18 黑色',
    bomType: 'MBOM',
    currentVersion: 'A.2',
    status: 'developing',
    materialCost: 9.2,
    processCost: 3.1,
    totalCost: 12.3,
    supplierNote: '黑色色母锁价后即可冻结。',
    updatedAt: '2026-06-09'
  },
  {
    productId: 104,
    productCode: 'PRD-LJ30-001',
    productName: '亮甲 3.0 镜面手机壳',
    bomType: 'PACK',
    currentVersion: 'B.1',
    status: 'released',
    materialCost: 27.4,
    processCost: 6.1,
    totalCost: 33.5,
    supplierNote: '包装版本已冻结，可直接追溯。',
    updatedAt: '2026-05-29'
  }
]

export function getFoundationProducts() {
  return mockResolve(() => clone(foundationProducts))
}

export function getFileSections() {
  return mockResolve(() => clone(fileSections))
}

export function getTestCenterSnapshot() {
  return mockResolve(() => ({
    categories: clone(testCategories),
    records: clone(testRecords)
  }))
}

export function getInventoryCenterSnapshot() {
  return mockResolve(() => ({
    tree: clone(inventoryTree),
    items: clone(inventoryItems)
  }))
}

export function getBomCenterRows() {
  return mockResolve(() => clone(bomCenterRows))
}

export function getProductPresentation(productId: number) {
  return mockResolve(() => clone(productDetailPresentationMap[productId] || productDetailPresentationMap[101]))
}
