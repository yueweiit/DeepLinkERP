import type { ProcessCenterSnapshot, ProcessRouteDetail, ProcessRouteListItem } from '@/types/process'

const routeList: ProcessRouteListItem[] = [
  {
    routeId: 501,
    routeCode: 'PROC-SC30-A',
    routeName: '超队 3.0 标准工艺路线',
    productId: 101,
    productCode: 'PRD-SC30-0001',
    productName: '超队 3.0',
    versionNo: 'A',
    routeType: 'new_product_line',
    status: 'locked',
    templateSource: 'standard',
    owner: '刘浩',
    operationCount: 9,
    totalCost: 8.5,
    currentGate: '签样确认',
    riskLevel: 'medium',
    hasExternalOperation: true,
    hasDifferenceOperation: false,
    updatedAt: '2026-06-08',
    targetPath: '/products/101'
  },
  {
    routeId: 502,
    routeCode: 'PROC-SC30-IP18-BLK-A',
    routeName: '超队 3.0 iPhone18 黑色差异工艺',
    productId: 102,
    productCode: 'PRD-SC30-IP18-BLK-A',
    productName: '超队 3.0 iPhone18 黑色',
    versionNo: 'A',
    routeType: 'new_model_variant',
    status: 'confirmed',
    templateSource: 'inherited',
    owner: '刘浩',
    operationCount: 7,
    totalCost: 3.9,
    currentGate: '差异测试验证',
    riskLevel: 'high',
    hasExternalOperation: true,
    hasDifferenceOperation: true,
    updatedAt: '2026-06-10',
    targetPath: '/products/102'
  },
  {
    routeId: 503,
    routeCode: 'PROC-LJ30-IP18-PNK-B',
    routeName: '亮甲 3.0 iPhone18 粉色子版本工艺',
    productId: 103,
    productCode: 'PRD-LJ30-IP18-PNK-B',
    productName: '亮甲 3.0 iPhone18 粉色',
    versionNo: 'B',
    routeType: 'new_model_variant',
    status: 'released',
    templateSource: 'inherited',
    owner: '赵越',
    operationCount: 6,
    totalCost: 2.8,
    currentGate: '正式发布',
    riskLevel: 'low',
    hasExternalOperation: false,
    hasDifferenceOperation: true,
    updatedAt: '2026-05-27',
    targetPath: '/products/103'
  }
]

const routeDetails = {
  501: {
    routeId: 501,
    routeCode: 'PROC-SC30-A',
    routeName: '超队 3.0 标准工艺路线',
    productId: 101,
    productCode: 'PRD-SC30-0001',
    productName: '超队 3.0',
    versionNo: 'A',
    routeType: 'new_product_line',
    status: 'locked',
    templateSource: 'standard',
    owner: '刘浩',
    currentGate: '签样确认',
    totalCost: 8.5,
    passedGate: true,
    isLocked: true,
    differenceOperationCount: 0,
    inheritedFrom: null,
    overviewNote: '作为新产品线工艺主版本，已完成工程、采购、质量三方确认，可作为后续子版本继承基线。',
    operations: [
      {
        operationId: 1,
        sequenceNo: 10,
        operationName: '注塑成型',
        operationType: '成型',
        workstationName: 'WS-INJ-01 注塑机',
        supplierName: null,
        parameterSummary: '温度 210C / 压力 80MPa / 周期 25s',
        qualityRequirement: '尺寸偏差 ±0.10mm',
        unitCost: 1.2,
        leadDays: 1,
        attachmentStatus: 'complete',
        isKeyProcess: true,
        isExternalOperation: false,
        isDifferenceOperation: false,
        changedInCurrentVersion: false
      },
      {
        operationId: 2,
        sequenceNo: 20,
        operationName: 'CNC 修边',
        operationType: '修边',
        workstationName: 'WS-CNC-03 CNC 修边位',
        supplierName: null,
        parameterSummary: '边角公差 0.05mm / 批次首件复核',
        qualityRequirement: '无毛刺 / 无崩边',
        unitCost: 0.8,
        leadDays: 1,
        attachmentStatus: 'complete',
        isKeyProcess: false,
        isExternalOperation: false,
        isDifferenceOperation: false,
        changedInCurrentVersion: false
      },
      {
        operationId: 3,
        sequenceNo: 30,
        operationName: '清洁处理',
        operationType: '前处理',
        workstationName: 'WS-CLN-02 清洗位',
        supplierName: null,
        parameterSummary: '无尘布 + 静电除尘',
        qualityRequirement: '不得残留油污和粉尘',
        unitCost: 0.3,
        leadDays: 1,
        attachmentStatus: 'complete',
        isKeyProcess: false,
        isExternalOperation: false,
        isDifferenceOperation: false,
        changedInCurrentVersion: false
      },
      {
        operationId: 4,
        sequenceNo: 40,
        operationName: '表面喷涂',
        operationType: '外协喷涂',
        workstationName: '外协喷涂线',
        supplierName: '东莞喷涂 A',
        parameterSummary: '雾化等级 3 / 烘烤 60C 20min',
        qualityRequirement: '色差 <= DeltaE 2',
        unitCost: 2.8,
        leadDays: 3,
        attachmentStatus: 'partial',
        isKeyProcess: true,
        isExternalOperation: true,
        isDifferenceOperation: false,
        changedInCurrentVersion: false
      },
      {
        operationId: 5,
        sequenceNo: 50,
        operationName: '磁铁装配',
        operationType: '装配',
        workstationName: 'WS-ASM-05 磁吸装配位',
        supplierName: '惠州磁材 C',
        parameterSummary: '治具压装 / N52 磁吸测试',
        qualityRequirement: '吸附力达标 / 装配方向一致',
        unitCost: 1.5,
        leadDays: 1,
        attachmentStatus: 'complete',
        isKeyProcess: true,
        isExternalOperation: false,
        isDifferenceOperation: false,
        changedInCurrentVersion: false
      },
      {
        operationId: 6,
        sequenceNo: 60,
        operationName: '贴合组装',
        operationType: '组装',
        workstationName: 'WS-ASM-09 贴合位',
        supplierName: null,
        parameterSummary: '贴合压力 0.4MPa / 固化 15min',
        qualityRequirement: '不得起翘 / 不得溢胶',
        unitCost: 0.9,
        leadDays: 1,
        attachmentStatus: 'complete',
        isKeyProcess: false,
        isExternalOperation: false,
        isDifferenceOperation: false,
        changedInCurrentVersion: false
      },
      {
        operationId: 7,
        sequenceNo: 70,
        operationName: '外观检验',
        operationType: '质量检验',
        workstationName: 'WS-QC-01 全检台',
        supplierName: null,
        parameterSummary: 'AQL 1.0 / 色差板对照',
        qualityRequirement: '外观全检合格',
        unitCost: 0.4,
        leadDays: 1,
        attachmentStatus: 'complete',
        isKeyProcess: true,
        isExternalOperation: false,
        isDifferenceOperation: false,
        changedInCurrentVersion: false
      },
      {
        operationId: 8,
        sequenceNo: 80,
        operationName: '功能测试',
        operationType: '质量检验',
        workstationName: 'WS-QA-02 测试位',
        supplierName: null,
        parameterSummary: '磁吸 / 按键 / 孔位抽检',
        qualityRequirement: '关键功能全部通过',
        unitCost: 0.3,
        leadDays: 1,
        attachmentStatus: 'complete',
        isKeyProcess: true,
        isExternalOperation: false,
        isDifferenceOperation: false,
        changedInCurrentVersion: false
      },
      {
        operationId: 9,
        sequenceNo: 90,
        operationName: '包装',
        operationType: '包装',
        workstationName: 'WS-PKG-01 包装线',
        supplierName: '东莞包材 D',
        parameterSummary: '彩盒 + 说明书 + 条码校验',
        qualityRequirement: '条码可扫 / 配件齐套',
        unitCost: 0.3,
        leadDays: 1,
        attachmentStatus: 'partial',
        isKeyProcess: false,
        isExternalOperation: false,
        isDifferenceOperation: false,
        changedInCurrentVersion: false
      }
    ],
    confirmations: [
      {
        roleName: '工程确认',
        ownerName: '刘浩',
        status: 'approved',
        note: '结构、工序顺序和参数已锁定。',
        confirmedAt: '2026-06-05 10:20'
      },
      {
        roleName: '采购确认',
        ownerName: '李采',
        status: 'approved',
        note: '外协喷涂和包材供应商已确认单价与交期。',
        confirmedAt: '2026-06-05 14:30'
      },
      {
        roleName: '质量确认',
        ownerName: '王质',
        status: 'approved',
        note: '关键检验标准和红样测试项已覆盖。',
        confirmedAt: '2026-06-05 17:00'
      }
    ],
    gateChecks: [
      { gateName: '关键工艺路径明确', passed: true, note: '注塑、喷涂、磁吸、检验链路完整。' },
      { gateName: '关键供应商明确', passed: true, note: '喷涂和包材外协已完成确认。' },
      { gateName: '质量标准完整', passed: true, note: 'SIP、SOP 和检验标准已绑定。' }
    ],
    attachments: [
      {
        operationName: '注塑成型',
        sopCount: 1,
        sipCount: 1,
        parameterSheetCount: 1,
        qualitySpecCount: 1,
        status: 'complete',
        updatedAt: '2026-06-05 10:00'
      },
      {
        operationName: '表面喷涂',
        sopCount: 1,
        sipCount: 0,
        parameterSheetCount: 1,
        qualitySpecCount: 1,
        status: 'partial',
        updatedAt: '2026-06-05 13:00'
      },
      {
        operationName: '包装',
        sopCount: 1,
        sipCount: 0,
        parameterSheetCount: 0,
        qualitySpecCount: 1,
        status: 'partial',
        updatedAt: '2026-06-05 18:20'
      }
    ],
    changes: [
      {
        versionNo: 'A',
        changeType: '首版锁定',
        changeReason: '完成签样确认后冻结标准工艺路线。',
        affectedOperations: ['表面喷涂', '磁铁装配'],
        costDelta: 0,
        leadDayDelta: 0,
        ownerName: '刘浩',
        changedAt: '2026-06-05 18:00'
      }
    ],
    impacts: [
      { label: '产品详情', summary: '查看当前产品主数据、流程与版本记录。', targetPath: '/products/101' },
      { label: 'BOM 资料', summary: '核对工艺成本与组件结构是否一致。', targetPath: '/bom' },
      { label: '质量管理', summary: '查看红样测试与检验标准执行情况。', targetPath: '/quality' },
      { label: '成本报价', summary: '核对工艺加工费对报价的影响。', targetPath: '/costs' }
    ]
  },
  502: {
    routeId: 502,
    routeCode: 'PROC-SC30-IP18-BLK-A',
    routeName: '超队 3.0 iPhone18 黑色差异工艺',
    productId: 102,
    productCode: 'PRD-SC30-IP18-BLK-A',
    productName: '超队 3.0 iPhone18 黑色',
    versionNo: 'A',
    routeType: 'new_model_variant',
    status: 'confirmed',
    templateSource: 'inherited',
    owner: '刘浩',
    currentGate: '差异测试验证',
    totalCost: 3.9,
    passedGate: false,
    isLocked: false,
    differenceOperationCount: 4,
    inheritedFrom: '超队 3.0 标准工艺路线 A',
    overviewNote: '继承父产品工艺主线，只补充 iPhone18 孔位、黑色色母和差异验证相关工序。',
    operations: [
      {
        operationId: 11,
        sequenceNo: 10,
        operationName: '孔位差异确认',
        operationType: '结构差异',
        workstationName: 'WS-ENG-01 工程评审位',
        supplierName: null,
        parameterSummary: 'iPhone18 摄像头位 / 按键位校核',
        qualityRequirement: '孔位匹配无干涉',
        unitCost: 0.4,
        leadDays: 1,
        attachmentStatus: 'complete',
        isKeyProcess: true,
        isExternalOperation: false,
        isDifferenceOperation: true,
        changedInCurrentVersion: true
      },
      {
        operationId: 12,
        sequenceNo: 20,
        operationName: '改模确认',
        operationType: '模具处理',
        workstationName: '模具评审位',
        supplierName: '东莞模具 C',
        parameterSummary: '沿用父模，调整孔位 insert',
        qualityRequirement: '试模后孔位与按键反馈达标',
        unitCost: 1.1,
        leadDays: 3,
        attachmentStatus: 'partial',
        isKeyProcess: true,
        isExternalOperation: true,
        isDifferenceOperation: true,
        changedInCurrentVersion: true
      },
      {
        operationId: 13,
        sequenceNo: 30,
        operationName: '黑色色母确认',
        operationType: '组件差异',
        workstationName: 'WS-MAT-02 材料确认位',
        supplierName: '东莞塑胶 A',
        parameterSummary: 'TPU 黑色色母批次验证',
        qualityRequirement: '颜色一致 / 不迁移',
        unitCost: 0.6,
        leadDays: 2,
        attachmentStatus: 'partial',
        isKeyProcess: false,
        isExternalOperation: false,
        isDifferenceOperation: true,
        changedInCurrentVersion: true
      },
      {
        operationId: 14,
        sequenceNo: 40,
        operationName: '试模打样',
        operationType: '样品确认',
        workstationName: 'WS-SMP-01 打样位',
        supplierName: null,
        parameterSummary: '1-2 轮差异样验证',
        qualityRequirement: '孔位 / 手感 / 外观通过',
        unitCost: 0.7,
        leadDays: 2,
        attachmentStatus: 'complete',
        isKeyProcess: true,
        isExternalOperation: false,
        isDifferenceOperation: true,
        changedInCurrentVersion: true
      },
      {
        operationId: 15,
        sequenceNo: 50,
        operationName: '差异测试验证',
        operationType: '质量检验',
        workstationName: 'WS-QA-02 测试位',
        supplierName: null,
        parameterSummary: '孔位匹配 / 按键手感 / 色牢度',
        qualityRequirement: '只测变化部分，不跑全量套件',
        unitCost: 0.5,
        leadDays: 2,
        attachmentStatus: 'partial',
        isKeyProcess: true,
        isExternalOperation: false,
        isDifferenceOperation: true,
        changedInCurrentVersion: true
      },
      {
        operationId: 16,
        sequenceNo: 60,
        operationName: '生产资料增量修改',
        operationType: '资料准备',
        workstationName: '工程资料位',
        supplierName: null,
        parameterSummary: '在父版 SIP/SOP 上补充参数差异',
        qualityRequirement: '差异参数与检验口径齐套',
        unitCost: 0.3,
        leadDays: 1,
        attachmentStatus: 'missing',
        isKeyProcess: false,
        isExternalOperation: false,
        isDifferenceOperation: true,
        changedInCurrentVersion: true
      },
      {
        operationId: 17,
        sequenceNo: 70,
        operationName: '小批量验证',
        operationType: '产线验证',
        workstationName: '试产线 2',
        supplierName: null,
        parameterSummary: '少量产线跑通 / 墨西哥前验证',
        qualityRequirement: '工艺节拍与不良率达标',
        unitCost: 0.3,
        leadDays: 2,
        attachmentStatus: 'missing',
        isKeyProcess: true,
        isExternalOperation: false,
        isDifferenceOperation: false,
        changedInCurrentVersion: false
      }
    ],
    confirmations: [
      {
        roleName: '工程确认',
        ownerName: '刘浩',
        status: 'approved',
        note: '父产品继承边界和差异工序已确认。',
        confirmedAt: '2026-06-06 09:20'
      },
      {
        roleName: '采购确认',
        ownerName: '李采',
        status: 'pending',
        note: '黑色色母单价和改模外协交期待回签。',
        confirmedAt: null
      },
      {
        roleName: '质量确认',
        ownerName: '王质',
        status: 'blocked',
        note: '差异测试验证记录未补齐，暂不能锁定。',
        confirmedAt: null
      }
    ],
    gateChecks: [
      { gateName: '父产品继承边界明确', passed: true, note: '已定义沿用父工艺与差异工序范围。' },
      { gateName: '差异供应商与参数明确', passed: false, note: '黑色色母成本和改模交期未最终确认。' },
      { gateName: '差异测试资料齐套', passed: false, note: '差异测试记录和增量 SIP 未补齐。' }
    ],
    attachments: [
      {
        operationName: '孔位差异确认',
        sopCount: 0,
        sipCount: 1,
        parameterSheetCount: 1,
        qualitySpecCount: 1,
        status: 'complete',
        updatedAt: '2026-06-06 08:50'
      },
      {
        operationName: '改模确认',
        sopCount: 1,
        sipCount: 0,
        parameterSheetCount: 1,
        qualitySpecCount: 0,
        status: 'partial',
        updatedAt: '2026-06-06 12:00'
      },
      {
        operationName: '生产资料增量修改',
        sopCount: 0,
        sipCount: 0,
        parameterSheetCount: 0,
        qualitySpecCount: 0,
        status: 'missing',
        updatedAt: '2026-06-06 18:10'
      }
    ],
    changes: [
      {
        versionNo: 'A',
        changeType: '新型号差异首版',
        changeReason: '客户要求 iPhone18 黑色版本，需要局部改模和色母变更。',
        affectedOperations: ['孔位差异确认', '改模确认', '黑色色母确认', '差异测试验证'],
        costDelta: 1.4,
        leadDayDelta: 3,
        ownerName: '刘浩',
        changedAt: '2026-06-06 18:30'
      }
    ],
    impacts: [
      { label: '产品详情', summary: '查看新型号差异流程、BOM 和版本节点。', targetPath: '/products/102' },
      { label: 'BOM 资料', summary: '核对黑色色母与替代料的差异 BOM。', targetPath: '/bom' },
      { label: '供应商管理', summary: '跟进改模外协与色母供应商回签。', targetPath: '/suppliers' },
      { label: '生产执行', summary: '查看小批量验证与 MX 前准备。', targetPath: '/production-orders' }
    ]
  },
  503: {
    routeId: 503,
    routeCode: 'PROC-LJ30-IP18-PNK-B',
    routeName: '亮甲 3.0 iPhone18 粉色子版本工艺',
    productId: 103,
    productCode: 'PRD-LJ30-IP18-PNK-B',
    productName: '亮甲 3.0 iPhone18 粉色',
    versionNo: 'B',
    routeType: 'new_model_variant',
    status: 'released',
    templateSource: 'inherited',
    owner: '赵越',
    currentGate: '正式发布',
    totalCost: 2.8,
    passedGate: true,
    isLocked: true,
    differenceOperationCount: 3,
    inheritedFrom: '亮甲 3.0 标准工艺路线 A',
    overviewNote: '子版本已发布，当前作为标准粉色机型的差异工艺基线供后续复用。',
    operations: [
      {
        operationId: 21,
        sequenceNo: 10,
        operationName: '配色确认',
        operationType: '组件差异',
        workstationName: 'WS-MAT-03 调色位',
        supplierName: '深圳板材 B',
        parameterSummary: '粉色面层纹理与色板确认',
        qualityRequirement: '外观一致 / 色差达标',
        unitCost: 0.5,
        leadDays: 1,
        attachmentStatus: 'complete',
        isKeyProcess: true,
        isExternalOperation: false,
        isDifferenceOperation: true,
        changedInCurrentVersion: true
      },
      {
        operationId: 22,
        sequenceNo: 20,
        operationName: '贴合参数微调',
        operationType: '参数差异',
        workstationName: 'WS-ASM-11 贴合位',
        supplierName: null,
        parameterSummary: '贴合时间 +10s / 压力微调',
        qualityRequirement: '无气泡 / 无偏位',
        unitCost: 0.6,
        leadDays: 1,
        attachmentStatus: 'complete',
        isKeyProcess: true,
        isExternalOperation: false,
        isDifferenceOperation: true,
        changedInCurrentVersion: true
      },
      {
        operationId: 23,
        sequenceNo: 30,
        operationName: '差异样确认',
        operationType: '样品确认',
        workstationName: 'WS-SMP-01 打样位',
        supplierName: null,
        parameterSummary: '粉色版本客户确认样',
        qualityRequirement: '颜色和贴合效果通过',
        unitCost: 0.7,
        leadDays: 1,
        attachmentStatus: 'complete',
        isKeyProcess: true,
        isExternalOperation: false,
        isDifferenceOperation: true,
        changedInCurrentVersion: true
      },
      {
        operationId: 24,
        sequenceNo: 40,
        operationName: '差异测试验证',
        operationType: '质量检验',
        workstationName: 'WS-QA-02 测试位',
        supplierName: null,
        parameterSummary: '只测颜色牢度与贴合耐久',
        qualityRequirement: '差异项全部通过',
        unitCost: 0.5,
        leadDays: 1,
        attachmentStatus: 'complete',
        isKeyProcess: true,
        isExternalOperation: false,
        isDifferenceOperation: true,
        changedInCurrentVersion: false
      },
      {
        operationId: 25,
        sequenceNo: 50,
        operationName: '增量资料冻结',
        operationType: '资料准备',
        workstationName: '工程资料位',
        supplierName: null,
        parameterSummary: '增量 SIP / 检验标准 / 包装版式',
        qualityRequirement: '差异资料全套冻结',
        unitCost: 0.2,
        leadDays: 1,
        attachmentStatus: 'complete',
        isKeyProcess: false,
        isExternalOperation: false,
        isDifferenceOperation: true,
        changedInCurrentVersion: false
      },
      {
        operationId: 26,
        sequenceNo: 60,
        operationName: '小批量跑线',
        operationType: '产线验证',
        workstationName: 'MX 试产线',
        supplierName: null,
        parameterSummary: '墨西哥端试产跑线确认',
        qualityRequirement: '产线节拍和质量稳定',
        unitCost: 0.3,
        leadDays: 2,
        attachmentStatus: 'complete',
        isKeyProcess: true,
        isExternalOperation: false,
        isDifferenceOperation: false,
        changedInCurrentVersion: false
      }
    ],
    confirmations: [
      {
        roleName: '工程确认',
        ownerName: '赵越',
        status: 'approved',
        note: '差异工艺已冻结并发布。',
        confirmedAt: '2026-05-27 11:00'
      },
      {
        roleName: '采购确认',
        ownerName: '李采',
        status: 'approved',
        note: '板材和包装物料价格已锁定。',
        confirmedAt: '2026-05-27 14:20'
      },
      {
        roleName: '质量确认',
        ownerName: '王质',
        status: 'approved',
        note: '差异测试结果全部通过。',
        confirmedAt: '2026-05-27 17:00'
      }
    ],
    gateChecks: [
      { gateName: '差异工艺确认', passed: true, note: '差异项数量少，全部闭环。' },
      { gateName: '资料冻结完成', passed: true, note: '增量资料已全套冻结。' },
      { gateName: 'MX 端验证通过', passed: true, note: '墨西哥端试产跑通。' }
    ],
    attachments: [
      {
        operationName: '配色确认',
        sopCount: 0,
        sipCount: 1,
        parameterSheetCount: 1,
        qualitySpecCount: 1,
        status: 'complete',
        updatedAt: '2026-05-27 09:30'
      },
      {
        operationName: '增量资料冻结',
        sopCount: 1,
        sipCount: 1,
        parameterSheetCount: 1,
        qualitySpecCount: 1,
        status: 'complete',
        updatedAt: '2026-05-27 16:30'
      }
    ],
    changes: [
      {
        versionNo: 'B',
        changeType: '粉色子版本发布',
        changeReason: '针对北美渠道推出粉色机型，沿用父产品主工艺，仅增加差异配色与贴合参数。',
        affectedOperations: ['配色确认', '贴合参数微调', '差异样确认'],
        costDelta: 0.8,
        leadDayDelta: 1,
        ownerName: '赵越',
        changedAt: '2026-05-27 18:00'
      }
    ],
    impacts: [
      { label: '产品详情', summary: '查看已发布子版本的完整业务信息。', targetPath: '/products/103' },
      { label: '质量管理', summary: '查看差异测试结果与发布前验证记录。', targetPath: '/quality' },
      { label: '文件中心', summary: '查看已冻结的增量资料。', targetPath: '/files' }
    ]
  }
} as unknown as Record<number, ProcessRouteDetail>

function resolveOperationConfirmer(detail: ProcessRouteDetail, operation: ProcessRouteDetail['operations'][number]) {
  const isQualityOperation = operation.operationType.includes('质量') || operation.operationName.includes('检验') || operation.operationName.includes('测试')
  const isPurchaseOperation = operation.isExternalOperation || Boolean(operation.supplierName)

  if (isQualityOperation) {
    return {
      confirmerName: '王质',
      confirmerRole: '品质确认'
    }
  }

  if (isPurchaseOperation) {
    return {
      confirmerName: '李采',
      confirmerRole: '采购确认'
    }
  }

  return {
    confirmerName: detail.owner,
    confirmerRole: '工程确认'
  }
}

Object.values(routeDetails).forEach((detail) => {
  detail.canFinalize = detail.status !== 'released'
  detail.canApplyChange = detail.status === 'locked' || detail.status === 'released'
  detail.operations = detail.operations.map((operation) => ({
    ...operation,
    ...resolveOperationConfirmer(detail, operation)
  }))
  detail.attachments = detail.attachments.map((attachment) => {
    const operation = detail.operations.find((item) => item.operationName === attachment.operationName)
    return {
      ...attachment,
      operationId: operation?.operationId,
      previewPath: `/files?processRouteId=${detail.routeId}&operationId=${operation?.operationId || ''}`,
      canAdd: true
    }
  })
  detail.changes = detail.changes.map((change) => ({
    ...change,
    canFinalize: detail.canFinalize,
    canApplyChange: detail.canApplyChange
  }))
})

export const processCenterData: ProcessCenterSnapshot = {
  metrics: [
    { label: '工艺路线总数', value: 3, hint: '当前前端模拟 1 条新产品线 + 2 条新型号差异路线。' },
    { label: '待锁定路线', value: 1, hint: '仍有 1 条差异路线未通过门禁，不可直接冻结。' },
    { label: '外协工序', value: 3, hint: '喷涂、改模、包材等需同步采购与交期确认。' },
    { label: '差异工序', value: 7, hint: '新型号只管理差异工序，不重复维护父产品全量工序。' }
  ],
  routes: routeList,
  routeDetails,
  templates: [
    {
      templateKey: 'magnetic-case-standard',
      templateName: '磁吸手机壳标准工艺',
      category: '新产品线',
      operationCount: 9,
      summary: '适用于磁吸壳标准开发，从注塑、喷涂、磁吸装配到全检和包装。',
      highlightedSteps: ['注塑成型', '表面喷涂', '磁铁装配', '功能测试']
    },
    {
      templateKey: 'variant-inherited-diff',
      templateName: '新型号继承差异模板',
      category: '新型号线',
      operationCount: 6,
      summary: '适用于已有父产品基础上创建新机型、新颜色或包装差异版本。',
      highlightedSteps: ['孔位差异确认', '改模判断', '差异测试验证', '增量资料冻结']
    }
  ]
}

export function getProcessRouteByProductId(productId: number) {
  return routeList.find((item) => item.productId === productId) || null
}

export function getProcessRouteDetail(routeId: number) {
  return routeDetails[routeId] || null
}
