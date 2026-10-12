import type {
  ApprovalStep,
  ApprovalTask,
  CommonStatus,
  DashboardSnapshot,
  MenuGroup,
  OperateLogEntry,
  UserOption,
  UserProfile
} from '@/types/common'
import type { BomCenterSnapshot } from '@/types/bom'
import type { CustomerDetail, CustomerSummary } from '@/types/customer'
import type {
  ProductCostBreakdownItem,
  ProductDetail,
  ProductSummary,
  ProductTestItem
} from '@/types/product'
import type { SupplierCenterSnapshot } from '@/types/supplier'

const productTimeline = [
  {
    title: '客户/市场需求',
    time: '2026-05-28T09:00:00+08:00',
    owner: '销售 / 项目经理',
    status: 'draft' as CommonStatus,
    description: '完成客户需求、市场机会和内部产品规划归集，明确目标机型、成本、周期和测试要求。'
  },
  {
    title: '新产品线立项',
    time: '2026-05-29T11:00:00+08:00',
    owner: '项目经理 / 管理层',
    status: 'developing' as CommonStatus,
    description: '完成可行性、预估成本、开发周期、产能与风险评估后正式立项。'
  },
  {
    title: 'Product 建档',
    time: '2026-05-30T15:00:00+08:00',
    owner: '工程',
    status: 'developing' as CommonStatus,
    description: '建立 Product 主档，挂接责任人、型号、颜色、测试项、附件和 BOM 主版本。'
  },
  {
    title: '工艺与样品验证',
    time: '2026-06-04T10:00:00+08:00',
    owner: '工程 / 品质',
    status: 'developing' as CommonStatus,
    description: '推进打样、工艺确认和红样测试，验证结构、外观、工序和关键性能。'
  },
  {
    title: 'BOM 资料确认',
    time: '2026-06-06T16:00:00+08:00',
    owner: '工程 / 采购',
    status: 'developing' as CommonStatus,
    description: '确认 EBOM、MBOM、包装 BOM、替代料、主供应来源和目标成本。'
  },
  {
    title: '文件与质量资料冻结',
    time: null,
    owner: '工程 / 品质',
    status: 'pending' as CommonStatus,
    description: '冻结图纸、BOM、SOP、SIP、检验标准和客户确认资料。'
  },
  {
    title: 'Product 发布',
    time: null,
    owner: '工程 / 管理层',
    status: 'pending' as CommonStatus,
    description: '资料冻结和审批通过后发布正式版本，供量产和追溯使用。'
  },
  {
    title: '历史追溯',
    time: null,
    owner: '系统 / 业务团队',
    status: 'pending' as CommonStatus,
    description: '沉淀版本快照、审批记录、测试结论和变更历史。'
  }
]

const productApprovals: ApprovalStep[] = [
  {
    stepName: '立项确认',
    approver: '王总',
    status: 'approved',
    time: '2026-05-29T16:30:00+08:00',
    comment: '同意按新产品线推进，进入 Product 建档。'
  },
  {
    stepName: 'BOM 会签',
    approver: '李采',
    status: 'approved',
    time: '2026-06-02T09:15:00+08:00',
    comment: '关键材料、替代料、包装物料和主供应来源已确认。'
  },
  {
    stepName: '质量会签',
    approver: '品质主管',
    status: 'approved',
    time: '2026-06-04T18:10:00+08:00',
    comment: '红样测试记录齐备，可进入资料冻结准备。'
  },
  {
    stepName: '发布审批',
    approver: '王总',
    status: 'pending',
    time: null,
    comment: '待文件与质量资料冻结后确认正式发布。'
  }
]

const productLogs: OperateLogEntry[] = [
  {
    time: '2026-06-04T10:10:00+08:00',
    operator: '张敏',
    action: '将当前阶段推进到工艺与样品验证，并补录红样测试计划。',
    level: 'normal'
  },
  {
    time: '2026-06-06T19:20:00+08:00',
    operator: '赵越',
    action: '补录 BOM 差异确认说明，准备提交文件与质量资料冻结。',
    level: 'normal'
  }
]

const newProductLineTimeline = [
  {
    title: '客户/市场需求归集',
    phase: '立项阶段',
    time: '2026-05-28T09:00:00+08:00',
    owner: '销售 / 项目经理',
    status: 'approved' as CommonStatus,
    description: '完成客户需求、市场机会、目标机型范围、成本区间与测试范围收集。'
  },
  {
    title: '新产品线立项',
    phase: '立项阶段',
    gate: true,
    time: '2026-05-29T11:00:00+08:00',
    owner: '项目经理 / 管理层',
    status: 'approved' as CommonStatus,
    description: '输出立项说明、风险评估、目标周期与投入边界，作为完整新品流程入口。'
  },
  {
    title: 'Product 建档',
    phase: '立项阶段',
    time: '2026-05-30T15:00:00+08:00',
    owner: '工程',
    status: 'approved' as CommonStatus,
    description: '建立产品主档、责任人、版本、测试项、成本拆分与主资料索引。'
  },
  {
    title: '图纸与外观确认',
    phase: '设计验证阶段',
    gate: true,
    time: '2026-06-01T10:00:00+08:00',
    owner: '工程 / 供应商',
    status: 'approved' as CommonStatus,
    description: '完成结构图、外观图、包装草图与关键尺寸确认。'
  },
  {
    title: '开模申请',
    phase: '开模阶段',
    gate: true,
    time: '2026-06-02T14:00:00+08:00',
    owner: '工程 / 采购',
    status: 'approved' as CommonStatus,
    description: '提交完整开模资料并完成开模审批。'
  },
  {
    title: '模具制作与试模',
    phase: '开模阶段',
    time: '2026-06-03T18:00:00+08:00',
    owner: '模具供应商',
    status: 'approved' as CommonStatus,
    description: '完成模具制作、试模与结构修正，具备签样条件。'
  },
  {
    title: '签样确认',
    phase: '签样阶段',
    gate: true,
    time: '2026-06-04T09:30:00+08:00',
    owner: '项目经理 / 客户',
    status: 'approved' as CommonStatus,
    description: '锁定外观与结构版本，签样通过后方可推进量产资料。'
  },
  {
    title: '工艺路线与红样测试',
    phase: '工艺定型阶段',
    time: '2026-06-05T10:00:00+08:00',
    owner: '工程 / 品质',
    status: 'developing' as CommonStatus,
    description: '正在验证工艺路线、红样测试、磁吸力与表面耐磨结果。'
  },
  {
    title: 'BOM 资料确认',
    phase: '工艺定型阶段',
    gate: true,
    time: null,
    owner: '工程 / 采购',
    status: 'pending' as CommonStatus,
    description: '确认 EBOM、MBOM、包装 BOM、替代料与主供应来源。'
  },
  {
    title: '文件与质量资料冻结',
    phase: '测试验证阶段',
    gate: true,
    time: null,
    owner: '工程 / 品质',
    status: 'pending' as CommonStatus,
    description: '冻结图纸、SOP、SIP、检验标准、样品结论与客户确认资料。'
  },
  {
    title: 'Product 发布审批',
    phase: '投产发布阶段',
    gate: true,
    time: null,
    owner: '管理层',
    status: 'pending' as CommonStatus,
    description: '完成发布审批后进入正式发布与量产追溯阶段。'
  },
  {
    title: '历史追溯',
    phase: '投产发布阶段',
    time: null,
    owner: '系统 / 业务团队',
    status: 'pending' as CommonStatus,
    description: '沉淀版本快照、审批记录、测试结论与后续变更轨迹。'
  }
]

const newModelVariantTimeline = [
  {
    title: '选择父产品线',
    phase: '扩展确认阶段',
    time: '2026-06-01T09:00:00+08:00',
    owner: '项目经理',
    status: 'approved' as CommonStatus,
    variantTag: 'inherited' as const,
    description: '基于既有产品线继承基础图纸、工艺路线、BOM 和测试基线。'
  },
  {
    title: '新型号/颜色需求确认',
    phase: '扩展确认阶段',
    gate: true,
    time: '2026-06-02T11:30:00+08:00',
    owner: '项目经理 / 销售',
    status: 'approved' as CommonStatus,
    variantTag: 'difference' as const,
    description: '确认新增机型、颜色、渠道包装与差异边界，只做扩展不重走新品立项。'
  },
  {
    title: '差异图纸与外观确认',
    phase: '差异调整阶段',
    time: '2026-06-03T15:00:00+08:00',
    owner: '工程 / 供应商',
    status: 'approved' as CommonStatus,
    variantTag: 'difference' as const,
    description: '仅处理新机型孔位、尺寸和配色差异，不重做整套父图纸。'
  },
  {
    title: '改模判断',
    phase: '差异调整阶段',
    time: '2026-06-04T10:00:00+08:00',
    owner: '工程 / 模具工程师',
    status: 'approved' as CommonStatus,
    variantTag: 'optional' as const,
    description: '本版本沿用父模具，无需新开模，仅保留改模判断记录。'
  },
  {
    title: '差异组件与 BOM 确认',
    phase: '差异调整阶段',
    time: '2026-06-06T16:00:00+08:00',
    owner: '工程 / 采购',
    status: 'developing' as CommonStatus,
    variantTag: 'difference' as const,
    description: '正在确认黑色 TPU 替代料、渠道包装 BOM 与差异组件成本。'
  },
  {
    title: '样品确认与针对性测试',
    phase: '验证阶段',
    gate: true,
    time: null,
    owner: '工程 / 品质',
    status: 'pending' as CommonStatus,
    variantTag: 'difference' as const,
    description: '仅验证发生变化的样品、外观、包装和关键性能，不重复全量测试。'
  },
  {
    title: '版本冻结',
    phase: '发布阶段',
    gate: true,
    time: null,
    owner: '工程 / 品质',
    status: 'pending' as CommonStatus,
    variantTag: 'inherited' as const,
    description: '冻结差异图纸、差异 BOM、测试记录与渠道资料。'
  },
  {
    title: '子版本发布',
    phase: '发布阶段',
    gate: true,
    time: null,
    owner: '管理层',
    status: 'pending' as CommonStatus,
    variantTag: 'inherited' as const,
    description: '发布为父产品线下的子版本，进入后续追溯与变更管理。'
  }
]

const newProductLineApprovals: ApprovalStep[] = [
  {
    stepName: '立项审批',
    approver: '王总',
    status: 'approved',
    time: '2026-05-29T16:30:00+08:00',
    comment: '同意按新品完整流程推进。'
  },
  {
    stepName: '开模审批',
    approver: '管理层',
    status: 'approved',
    time: '2026-06-02T17:30:00+08:00',
    comment: '开模资料齐全，允许进入模具制作。'
  },
  {
    stepName: '资料冻结会签',
    approver: '品质主管',
    status: 'pending',
    time: null,
    comment: '待红样测试与 BOM 会签完成后提交冻结。'
  },
  {
    stepName: '发布审批',
    approver: '王总',
    status: 'pending',
    time: null,
    comment: '待冻结资料齐套后确认正式发布。'
  }
]

const newModelVariantApprovals: ApprovalStep[] = [
  {
    stepName: '扩展确认',
    approver: '王总',
    status: 'approved',
    time: '2026-06-02T18:00:00+08:00',
    comment: '同意以父产品线为基础做型号扩展。'
  },
  {
    stepName: '改模判断记录',
    approver: '模具工程师',
    status: 'approved',
    time: '2026-06-04T15:00:00+08:00',
    comment: '本版本无需新开模，沿用父模具。'
  },
  {
    stepName: '子版本发布审批',
    approver: '王总',
    status: 'pending',
    time: null,
    comment: '待差异 BOM、样品确认和版本冻结完成后发布。'
  }
]

const productLogsByProduct: Record<number, OperateLogEntry[]> = {
  101: [
    {
      time: '2026-06-04T10:10:00+08:00',
      operator: '张敏',
      action: '签样确认完成，推进到工艺路线与红样测试阶段。',
      level: 'normal'
    },
    {
      time: '2026-06-06T19:20:00+08:00',
      operator: '张敏',
      action: '补录新品 BOM 会签准备说明，待进入资料冻结关口。',
      level: 'normal'
    }
  ],
  102: [
    {
      time: '2026-06-04T15:20:00+08:00',
      operator: '刘浩',
      action: '完成差异图纸确认并记录无需新开模判断。',
      level: 'normal'
    },
    {
      time: '2026-06-06T18:40:00+08:00',
      operator: '刘浩',
      action: '补录黑色版本差异 BOM 说明，等待采购确认替代料成本。',
      level: 'normal'
    }
  ],
  103: [
    {
      time: '2026-05-24T16:00:00+08:00',
      operator: '赵越',
      action: '完成粉色版本针对性测试，提交子版本发布审批。',
      level: 'normal'
    },
    {
      time: '2026-05-28T09:00:00+08:00',
      operator: '赵越',
      action: '子版本发布完成并转入历史追溯。',
      level: 'normal'
    }
  ]
}

const variantParentProductMap: Record<number, string | null> = {
  101: null,
  102: '超星 3.0',
  103: '亮甲 3.0'
}

const testItemsByProduct: Record<number, ProductTestItem[]> = {
  101: [
    { name: '跌落测试', method: '1.2m 六面各两次', owner: '品质', frequency: '红样', result: '进行中', dueDate: '2026-06-08' },
    { name: '酒精测试', method: '95% 酒精 500 次', owner: '品质', frequency: '红样', result: '待执行', dueDate: '2026-06-09' },
    { name: '磁吸力测试', method: '标准磁吸治具', owner: '工程 / 品质', frequency: '试产前', result: '进行中', dueDate: '2026-06-10' },
    { name: '耐磨测试', method: '表面往复摩擦 1000 次', owner: '品质', frequency: '试产前', result: '待执行', dueDate: '2026-06-11' }
  ],
  102: [
    { name: '跌落测试', method: '1.2m 六面各两次', owner: '品质', frequency: '红样', result: '通过', dueDate: '2026-06-06' },
    { name: '酒精测试', method: '95% 酒精 500 次', owner: '品质', frequency: '红样', result: '进行中', dueDate: '2026-06-08' },
    { name: '包装跌落测试', method: '带彩盒跌落', owner: '品质', frequency: '发布前', result: '待执行', dueDate: '2026-06-12' }
  ],
  103: [
    { name: '跌落测试', method: '1.2m 六面各两次', owner: '品质', frequency: '红样', result: '通过', dueDate: '2026-05-18' },
    { name: '酒精测试', method: '95% 酒精 500 次', owner: '品质', frequency: '红样', result: '通过', dueDate: '2026-05-19' },
    { name: '磁吸力测试', method: '标准磁吸治具', owner: '工程 / 品质', frequency: '发布前', result: '通过', dueDate: '2026-05-20' },
    { name: '包装跌落测试', method: '带彩盒跌落', owner: '品质', frequency: '发布前', result: '通过', dueDate: '2026-05-22' }
  ]
}

const costBreakdownByProduct: Record<number, ProductCostBreakdownItem[]> = {
  101: [
    { category: '主材', amount: 18.2, ratio: 0.53, note: 'TPU + PC 主体结构' },
    { category: '功能件', amount: 7.6, ratio: 0.22, note: '磁吸组件与辅料' },
    { category: '包装', amount: 3.8, ratio: 0.11, note: '彩盒、标签、内托' },
    { category: '工艺', amount: 4.7, ratio: 0.14, note: '喷涂、镭雕、检验' }
  ],
  102: [
    { category: '主材', amount: 15.8, ratio: 0.5, note: 'TPU + PC' },
    { category: '功能件', amount: 6.9, ratio: 0.22, note: '磁吸组件与保护件' },
    { category: '包装', amount: 3.4, ratio: 0.11, note: '客户渠道彩盒' },
    { category: '工艺', amount: 5.3, ratio: 0.17, note: '喷涂、镭雕与装配' }
  ],
  103: [
    { category: '主材', amount: 16.4, ratio: 0.49, note: 'TPU + 镜面片' },
    { category: '功能件', amount: 7.2, ratio: 0.22, note: '装饰件与磁吸件' },
    { category: '包装', amount: 4.1, ratio: 0.12, note: '零售彩盒与条码标签' },
    { category: '工艺', amount: 5.8, ratio: 0.17, note: '镜面贴合与全检' }
  ]
}

export const dashboardData: DashboardSnapshot = {
  hero: {
    title: '手机壳制造业 PLM 工作台',
    subtitle: '围绕新产品开发、BOM 资料确认、样品验证、资料冻结与发布节点，统一看进度、风险、成本和待办。'
  },
  kpis: [
    { label: '进行中的产品', value: 18, trend: '+3，本周新增型号扩展', targetPath: '/products?status=developing' },
    { label: '待审批节点', value: 9, trend: '2 个超时，需管理层处理', targetPath: '/approval-tasks?status=pending' },
    { label: 'SKU 视图项目', value: 24, trend: '覆盖 7 个系列、12 个机型', targetPath: '/sku-view' },
    { label: '资料冻结缺口', value: 5, trend: 'SOP / SIP / BOM 待补齐', targetPath: '/products?frozen=unfrozen' }
  ],
  milestones: [
    {
      stage: '新产品线立项',
      owner: '项目经理 / 管理层',
      dueDate: '2026-06-06',
      status: 'confirmed',
      summary: '亮甲 3.0 系列已完成立项确认，进入 Product 建档与资料归集。',
      targetPath: '/products/103'
    },
    {
      stage: 'Product 建档',
      owner: '工程',
      dueDate: '2026-06-07',
      status: 'developing',
      summary: '超星 3.0 已完成主数据建档，正在补齐型号、颜色、测试项和成本拆分。',
      targetPath: '/products/101'
    },
    {
      stage: '工艺与样品验证',
      owner: '工程 / 品质',
      dueDate: '2026-06-10',
      status: 'developing',
      summary: '红样测试持续推进，正校验结构、外观、磁吸力和酒精测试结果。',
      targetPath: '/quality'
    },
    {
      stage: 'BOM 资料确认',
      owner: '工程 / 采购',
      dueDate: '2026-06-12',
      status: 'developing',
      summary: 'iPhone18 黑色版本正在核对 EBOM、包装 BOM、替代料与主供应来源。',
      targetPath: '/bom'
    },
    {
      stage: '文件与质量资料冻结',
      owner: '工程 / 品质',
      dueDate: '2026-06-14',
      status: 'pending',
      summary: '待冻结图纸、SOP、SIP、检验标准和客户确认资料后提交发布审批。',
      targetPath: '/products?frozen=unfrozen'
    }
  ],
  risks: [
    {
      title: '文件与质量资料未冻结',
      level: 'high',
      owner: '工程 / 品质',
      action: '先补齐 SOP、SIP、检验标准和客户确认件，再提交发布。',
      targetPath: '/products?frozen=unfrozen'
    },
    {
      title: '客户确认资料未归档',
      level: 'medium',
      owner: '销售',
      action: '补传签样确认书并挂接到当前 Product 版本。',
      targetPath: '/products/103'
    },
    {
      title: 'BOM 替代料待确认',
      level: 'medium',
      owner: '采购',
      action: '确认黑色 TPU 替代料价格、交期和适用范围。',
      targetPath: '/bom?risk=substitute'
    }
  ],
  stageOverview: [
    { stage: '立项', total: 6, delayed: 0, completionRate: 1, targetPath: '/projects' },
    { stage: '建档', total: 9, delayed: 1, completionRate: 0.82, targetPath: '/products' },
    { stage: '样品验证', total: 7, delayed: 2, completionRate: 0.68, targetPath: '/quality' },
    { stage: 'BOM 确认', total: 5, delayed: 1, completionRate: 0.74, targetPath: '/bom' },
    { stage: '资料冻结', total: 4, delayed: 2, completionRate: 0.43, targetPath: '/products?frozen=unfrozen' }
  ],
  focusItems: [
    {
      title: '超星 3.0 新产品线',
      owner: '张敏',
      dueDate: '2026-06-10',
      status: 'developing',
      summary: '需完成红样测试与预估成本复核，随后进入 BOM 资料确认。',
      targetPath: '/products/101'
    },
    {
      title: 'iPhone18 黑色型号扩展',
      owner: '刘浩',
      dueDate: '2026-06-12',
      status: 'developing',
      summary: '当前处于 BOM 会签阶段，替代料成本与包装 BOM 待锁定。',
      targetPath: '/products/102'
    },
    {
      title: '亮甲 3.0 北美渠道版本',
      owner: '赵越',
      dueDate: '2026-06-14',
      status: 'pending',
      summary: '客户确认资料归档后可直接进入历史追溯状态。',
      targetPath: '/products/103'
    }
  ],
  todoItems: [
    { title: '补录超星 3.0 酒精测试结果', owner: '品质', dueDate: '2026-06-09', tag: '测试项', targetPath: '/products/101' },
    { title: '确认黑色 TPU 替代料报价', owner: '采购', dueDate: '2026-06-10', tag: 'BOM 成本', targetPath: '/bom?risk=substitute' },
    { title: '完善亮甲 3.0 客户确认资料', owner: '销售', dueDate: '2026-06-11', tag: '资料冻结', targetPath: '/products/103' },
    { title: '复核新产品线预估成本拆分', owner: '财务 / 项目经理', dueDate: '2026-06-12', tag: '成本', targetPath: '/products?status=developing' }
  ]
}

export const approvalTasks: ApprovalTask[] = [
  {
    taskId: 1,
    objectType: 'product',
    objectName: '超星 3.0 / iPhone18 / 黑色',
    nodeName: '发布审批',
    initiator: '刘浩',
    approver: '王总',
    dueDate: '2026-06-12',
    status: 'pending',
    targetPath: '/products/102'
  },
  {
    taskId: 2,
    objectType: 'order',
    objectName: '亮甲 3.0 墨西哥客户样品需求',
    nodeName: '品质确认',
    initiator: '张敏',
    approver: '品质主管',
    dueDate: '2026-06-07',
    status: 'approved',
    targetPath: '/orders'
  },
  {
    taskId: 3,
    objectType: 'product',
    objectName: '超星 3.0 新产品线',
    nodeName: '资料冻结确认',
    initiator: '张敏',
    approver: '张敏',
    dueDate: '2026-06-10',
    status: 'pending',
    targetPath: '/products/101'
  }
]

export const productList: ProductSummary[] = [
  {
    productId: 101,
    productCode: 'PRD-SC30-0001',
    productName: '超星 3.0',
    productType: 'product_line',
    seriesName: '超星',
    model: '--',
    color: '--',
    material: 'TPU + PC + 磁吸组件',
    ownerUserName: '张敏',
    versionNo: 'A',
    status: 'developing',
    currentStage: '工艺与样品验证',
    customerName: '内部新品规划',
    frozenFlag: false,
    releasedAt: null,
    completionRate: 0.68,
    estimatedCost: 34.3,
    estimatedCostCurrency: 'CNY',
    testItemCount: testItemsByProduct[101].length,
    activeBomVersion: 'EBOM-A.3'
  },
  {
    productId: 102,
    productCode: 'PRD-SC30-IP18-BLK-A',
    productName: '超星 3.0 iPhone18 黑色',
    productType: 'model_variant',
    seriesName: '超星',
    model: 'iPhone18',
    color: '黑色',
    material: 'TPU + PC',
    ownerUserName: '刘浩',
    versionNo: 'A',
    status: 'developing',
    currentStage: 'BOM 资料确认',
    customerName: '墨西哥客户 A',
    frozenFlag: false,
    releasedAt: null,
    completionRate: 0.84,
    estimatedCost: 31.4,
    estimatedCostCurrency: 'CNY',
    testItemCount: testItemsByProduct[102].length,
    activeBomVersion: 'MBOM-A.2'
  },
  {
    productId: 103,
    productCode: 'PRD-LJ30-IP18-PNK-B',
    productName: '亮甲 3.0 iPhone18 粉色',
    productType: 'model_variant',
    seriesName: '亮甲 3.0',
    model: 'iPhone18',
    color: '粉色',
    material: 'TPU + 镜面片',
    ownerUserName: '赵越',
    versionNo: 'B',
    status: 'released',
    currentStage: 'Product 发布',
    customerName: '北美渠道定制',
    frozenFlag: true,
    releasedAt: '2026-05-28T09:00:00+08:00',
    completionRate: 1,
    estimatedCost: 33.5,
    estimatedCostCurrency: 'CNY',
    testItemCount: testItemsByProduct[103].length,
    activeBomVersion: 'PACK-B.1'
  },
  {
    productId: 301,
    parentProductId: null,
    productCode: 'PRD-CD30-ARCH-001',
    productName: '超队 3.0',
    productType: 'product_line',
    seriesName: '超队',
    model: '--',
    color: '--',
    material: 'TPU + 磁吸组件',
    ownerUserName: '张经理',
    versionNo: 'A.3',
    status: 'archived',
    currentStage: '已归档',
    currentStepNo: 22,
    customerName: '北美渠道 A',
    frozenFlag: true,
    releasedAt: '2026-05-30T10:00:00+08:00',
    completionRate: 1,
    estimatedCost: 35.0,
    estimatedCostCurrency: 'CNY',
    testItemCount: 8,
    activeBomVersion: 'EBOM-A.3'
  },
  {
    productId: 302,
    parentProductId: 301,
    productCode: 'SKU-CD30-IP18-BLK',
    productName: '超队 3.0 iPhone18 黑色',
    productType: 'model_variant',
    seriesName: '超队',
    model: 'iPhone18',
    color: '黑色',
    material: 'TPU + PC',
    ownerUserName: '刘浩',
    versionNo: 'A.1',
    status: 'archived',
    currentStage: '已归档',
    currentStepNo: 16,
    customerName: '北美渠道 A',
    frozenFlag: true,
    releasedAt: '2026-06-02T15:00:00+08:00',
    completionRate: 1,
    estimatedCost: 13.8,
    estimatedCostCurrency: 'CNY',
    testItemCount: 5,
    activeBomVersion: 'MBOM-A.1'
  },
  {
    productId: 303,
    parentProductId: 301,
    productCode: 'SKU-CD30-IP18-TRS',
    productName: '超队 3.0 iPhone18 透明',
    productType: 'model_variant',
    seriesName: '超队',
    model: 'iPhone18',
    color: '透明',
    material: 'TPU',
    ownerUserName: '刘浩',
    versionNo: 'A.1',
    status: 'archived',
    currentStage: '已归档',
    currentStepNo: 16,
    customerName: '北美渠道 A',
    frozenFlag: true,
    releasedAt: '2026-06-03T09:00:00+08:00',
    completionRate: 1,
    estimatedCost: 12.5,
    estimatedCostCurrency: 'CNY',
    testItemCount: 4,
    activeBomVersion: 'MBOM-A.1'
  }
]

function buildTimeline(summary: ProductSummary) {
  if (summary.status === 'released') {
    return productTimeline.map((item, index) => ({
      ...item,
      time: item.time || `2026-06-${String(10 + index).padStart(2, '0')}T09:00:00+08:00`,
      status: item.status === 'pending' ? ('released' as CommonStatus) : item.status
    }))
  }

  if (summary.productId === 102) {
    return productTimeline.map((item) => {
      if (item.title === '文件与质量资料冻结' || item.title === 'Product 发布' || item.title === '历史追溯') {
        return item
      }
      return item
    })
  }

  return productTimeline
}

function makeVersionHistory(summary: ProductSummary) {
  const base = {
    versionNo: summary.versionNo,
    releasedAt: summary.releasedAt,
    releasedBy: summary.releasedAt ? summary.ownerUserName : '--',
    changeSummary: summary.status === 'released' ? '发布并冻结量产资料。' : '创建开发版本并推进标准流程。',
    status: summary.status,
    bomVersion: summary.activeBomVersion,
    estimatedCost: summary.estimatedCost,
    actualCost: summary.status === 'released' ? summary.estimatedCost - 0.8 : null
  }

  if (summary.productId === 103) {
    return [
      {
        versionNo: 'A',
        releasedAt: '2026-05-16T18:00:00+08:00',
        releasedBy: '赵越',
        changeSummary: '完成首轮发布，确认镜面片工艺与包装版本。',
        status: 'archived' as CommonStatus,
        bomVersion: 'PACK-A.4',
        estimatedCost: 34.8,
        actualCost: 34.2
      },
      base
    ]
  }

  return [
    {
      versionNo: `${summary.versionNo}-0`,
      releasedAt: '2026-05-31T12:00:00+08:00',
      releasedBy: summary.ownerUserName,
      changeSummary: '初版建档，建立基础测试项和 BOM 草案。',
      status: 'draft' as CommonStatus,
      bomVersion: `${summary.activeBomVersion}-draft`,
      estimatedCost: summary.estimatedCost + 1.4,
      actualCost: null
    },
    base
  ]
}

function makeProductDetail(summary: ProductSummary): ProductDetail {
  const costBreakdown =
    costBreakdownByProduct[summary.productId] ?? [
      {
        category: '基础成本',
        amount: summary.estimatedCost,
        ratio: 1,
        note: '由产品列表估算成本生成的默认明细'
      }
    ]
  const testItems = testItemsByProduct[summary.productId] ?? []

  return {
    productId: summary.productId,
    basicInfo: {
      productCode: summary.productCode,
      productName: summary.productName,
      seriesName: summary.seriesName,
      productType: summary.productType === 'product_line' ? '新产品产品线' : '型号扩展',
      productTypeLabel: summary.productType === 'product_line' ? '新产品产品线' : 'SKU 型号视图',
      ownerUserName: summary.ownerUserName,
      status: summary.status,
      versionNo: summary.versionNo,
      material: summary.material,
      packageType: '彩盒',
      surfaceProcess: summary.productId === 103 ? '高光镜面' : '喷涂 + 镭雕',
      coreProcess: '注塑 -> CNC / 打磨 -> 清胶 -> 表面处理 -> 沾磁铁 -> 包装 -> 成品全检',
      composition: 'TPU 边框 + PC 背板 + 功能组件',
      customerName: summary.customerName,
      currentStage: summary.currentStage,
      expectedReleaseDate: summary.productId === 103 ? '2026-05-28' : '2026-06-18',
      model: summary.model,
      color: summary.color,
      estimatedCost: summary.estimatedCost,
      estimatedCostCurrency: summary.estimatedCostCurrency
    },
    statusTimeline: buildTimeline(summary),
    approvalTimeline:
      summary.status === 'released'
        ? productApprovals.map((item, index) => ({
            ...item,
            status: 'approved',
            time: item.time || `2026-06-${String(12 + index).padStart(2, '0')}T16:00:00+08:00`
          }))
        : productApprovals,
    bomItems: [
      {
        inventoryCode: 'INV-MATERIAL-0023',
        inventoryName: 'TPU 原料 85A',
        quantity: 1.2,
        stockUom: 'kg',
        unitCost: 25.5,
        supplierName: '东莞塑胶 A'
      },
      {
        inventoryCode: 'INV-MAG-0045',
        inventoryName: 'N52 磁铁组件',
        quantity: 1,
        stockUom: 'set',
        unitCost: 3.6,
        supplierName: '惠州材料 C'
      },
      {
        inventoryCode: 'INV-PACK-0102',
        inventoryName: '渠道彩盒',
        quantity: 1,
        stockUom: 'pcs',
        unitCost: 1.4,
        supplierName: '东莞包材 D'
      }
    ],
    attachments: [
      {
        attachmentId: summary.productId,
        fileName: `${summary.productCode}_结构图纸_${summary.versionNo}.pdf`,
        fileCategory: 'drawing',
        versionNo: summary.versionNo,
        uploadedBy: '工程',
        uploadedAt: '2026-06-01T09:20:00+08:00',
        status: summary.status === 'released' ? 'released' : 'confirmed'
      },
      {
        attachmentId: summary.productId + 1000,
        fileName: `${summary.productCode}_测试计划_${summary.versionNo}.xlsx`,
        fileCategory: 'quality',
        versionNo: summary.versionNo,
        uploadedBy: '品质',
        uploadedAt: '2026-06-02T14:30:00+08:00',
        status: 'confirmed'
      }
    ],
    qualityRecords: testItems.map((item) => ({
      testItem: item.name,
      result: item.result,
      owner: item.owner,
      dueDate: item.dueDate
    })),
    operationLogs: productLogs,
    versionHistory: makeVersionHistory(summary),
    costBreakdown,
    testItems
  }
}

export const productDetails: Record<number, ProductDetail> = Object.fromEntries(
  productList.map((item) => [item.productId, makeProductDetail(item)])
)

export const customerList: CustomerSummary[] = [
  {
    customerId: 1,
    customerCode: 'CUS-MX-0001',
    customerName: '墨西哥客户 A',
    customerShortName: 'MX-A',
    countryCode: 'MX',
    contactName: 'Carlos',
    contactPhone: '+52-888-001',
    contactEmail: 'carlos@example.mx',
    status: 'active',
    updatedAt: '2026-06-04T10:00:00+08:00'
  },
  {
    customerId: 2,
    customerCode: 'CUS-US-0003',
    customerName: '北美渠道定制',
    customerShortName: 'US-Channel',
    countryCode: 'US',
    contactName: 'Emily',
    contactPhone: '+1-323-555-002',
    contactEmail: 'emily@example.com',
    status: 'active',
    updatedAt: '2026-06-03T15:00:00+08:00'
  },
  {
    customerId: 3,
    customerCode: 'CUS-CN-0008',
    customerName: '国内新品孵化',
    customerShortName: 'CN-LAB',
    countryCode: 'CN',
    contactName: '王娜',
    contactPhone: '13800001122',
    contactEmail: 'wangna@example.cn',
    status: 'draft',
    updatedAt: '2026-06-02T12:00:00+08:00'
  }
]

export const customerDetails: Record<number, CustomerDetail> = {
  1: {
    ...customerList[0],
    address: '墨西哥城 Reforma 101',
    sourceType: '客户定制',
    ownerUserName: '销售-林',
    relatedOrders: [
      {
        orderCode: 'ORD-SAMPLE-20260603-003',
        orderTitle: 'iPhone18 黑色样品需求',
        status: 'confirmed',
        productName: '超星 3.0 iPhone18 黑色'
      }
    ],
    operationLogs: [
      {
        time: '2026-06-04T10:00:00+08:00',
        operator: '销售-林',
        action: '更新客户联系人与样品交付偏好。',
        level: 'normal'
      }
    ]
  },
  2: {
    ...customerList[1],
    address: 'Los Angeles 8th Avenue',
    sourceType: '渠道客户',
    ownerUserName: '张敏',
    relatedOrders: [],
    operationLogs: [
      {
        time: '2026-06-03T15:00:00+08:00',
        operator: '张敏',
        action: '新建渠道客户档案。',
        level: 'normal'
      }
    ]
  },
  3: {
    ...customerList[2],
    address: '东莞长安研发中心',
    sourceType: '内部项目来源',
    ownerUserName: '项目经理-周',
    relatedOrders: [],
    operationLogs: [
      {
        time: '2026-06-02T12:00:00+08:00',
        operator: '项目经理-周',
        action: '创建内部新品孵化来源。',
        level: 'normal'
      }
    ]
  }
}

export const bomCenterData: BomCenterSnapshot = {
  metrics: [
    { label: 'BOM 完整率', value: '86%', hint: '5 个版本待补齐替代料与包装资料', targetPath: '/products?frozen=unfrozen' },
    { label: '已冻结版本', value: '18', hint: '发布前资料已锁版，可追溯', targetPath: '/products?frozen=frozen' },
    { label: '替代料待确认', value: '7', hint: '需采购确认报价、交期与适用范围', targetPath: '/suppliers' },
    { label: '包装 BOM 风险', value: '3', hint: '彩盒与标签版本仍待锁定', targetPath: '/products/102' }
  ],
  versions: [
    {
      bomId: 1,
      productId: 101,
      productCode: 'PRD-SC30-0001',
      productName: '超星 3.0',
      bomCode: 'BOM-SC30-EBOM',
      bomType: 'EBOM',
      bomVersion: 'A.3',
      owner: '张敏',
      status: 'developing',
      estimatedCost: 34.3,
      costDelta: 1.2,
      cumulativeCost: 42.8,
      completionRate: 0.82,
      supplierRiskNote: '磁吸组件替代料待确认',
      updatedAt: '2026-06-08T10:00:00+08:00',
      targetPath: '/products/101'
    },
    {
      bomId: 2,
      productId: 102,
      productCode: 'PRD-SC30-IP18-BLK-A',
      productName: '超星 3.0 iPhone18 黑色',
      bomCode: 'BOM-SC30-MBOM',
      bomType: 'MBOM',
      bomVersion: 'A.2',
      owner: '刘浩',
      status: 'developing',
      estimatedCost: 31.4,
      costDelta: -0.6,
      cumulativeCost: 38.1,
      completionRate: 0.88,
      supplierRiskNote: '黑色 TPU 单价待回签',
      updatedAt: '2026-06-08T11:20:00+08:00',
      targetPath: '/products/102'
    },
    {
      bomId: 3,
      productId: 103,
      productCode: 'PRD-LJ30-IP18-PNK-B',
      productName: '亮甲 3.0 iPhone18 粉色',
      bomCode: 'BOM-LJ30-PACK',
      bomType: 'PACK',
      bomVersion: 'B.1',
      owner: '赵越',
      status: 'released',
      estimatedCost: 33.5,
      costDelta: 0.9,
      cumulativeCost: 40.4,
      completionRate: 1,
      supplierRiskNote: '已锁版',
      updatedAt: '2026-05-28T09:00:00+08:00',
      targetPath: '/products/103'
    },
    {
      bomId: 4,
      productId: 103,
      productCode: 'PRD-LJ30-IP18-PNK-A',
      productName: '亮甲 3.0 iPhone18 粉色',
      bomCode: 'BOM-LJ30-PACK',
      bomType: 'PACK',
      bomVersion: 'A.4',
      owner: '赵越',
      status: 'archived',
      estimatedCost: 34.8,
      costDelta: 1.5,
      cumulativeCost: 39.5,
      completionRate: 1,
      supplierRiskNote: '历史版本',
      updatedAt: '2026-05-16T18:00:00+08:00',
      targetPath: '/products/103'
    }
  ],
  risks: [
    { title: '黑色 TPU 替代料未完成报价回签', level: 'medium', owner: '采购', action: '确认单价、交期并锁定适用版本', targetPath: '/suppliers' },
    { title: '包装标签版本未冻结', level: 'medium', owner: '工程', action: '补齐客户确认附件后执行锁版', targetPath: '/products/102' },
    { title: '磁吸组件来料稳定性待验证', level: 'high', owner: '品质 / 采购', action: '补做批次验证并更新 BOM 备注', targetPath: '/quality' }
  ],
  trend: [
    { versionLabel: 'A.1', estimatedCost: 30.8, changeLabel: '初版', targetPath: '/products/101' },
    { versionLabel: 'A.2', estimatedCost: 33.1, changeLabel: '+2.3', targetPath: '/products/101' },
    { versionLabel: 'A.3', estimatedCost: 34.3, changeLabel: '+1.2', targetPath: '/products/101' },
    { versionLabel: 'B.1', estimatedCost: 33.5, changeLabel: '-0.8', targetPath: '/products/103' }
  ]
}

export const supplierCenterData: SupplierCenterSnapshot = {
  metrics: [
    { label: '合作供应商', value: '28', hint: '材料、包材、模具供应侧统一维护', targetPath: '/suppliers' },
    { label: '待确认报价', value: '6', hint: '成本权限内查看并跟进回签', targetPath: '/costs' },
    { label: '交期风险', value: '3', hint: '影响打样与资料确认节奏', targetPath: '/suppliers' },
    { label: '资质缺口', value: '4', hint: 'RoHS / REACH / MSDS 待补齐', targetPath: '/quality' }
  ],
  suppliers: [
    {
      supplierId: 201,
      supplierCode: 'SUP-DG-PLASTIC-A',
      supplierName: '东莞塑胶 A',
      shortName: '塑胶A',
      contactPerson: '李工',
      contactPhone: '13800110001',
      contactEmail: 'ligong@plastic-a.com',
      supplyCategories: ['原材料', '功能件'],
      region: '东莞',
      status: 'active',
      updatedAt: '2026-06-08T09:30:00+08:00',
      cooperationLevel: '核心供应',
      paymentTerm: '月结 45 天',
      deliveryRisk: 'medium',
      supplyRecords: [
        { recordId: 1, supplyType: 'material', itemCode: 'INV-MATERIAL-0023', itemName: 'TPU 原料 85A', relatedProduct: '超星 3.0', unitPrice: 25.5, currency: 'CNY', lastDeliveryDate: '2026-06-05', status: 'available', targetPath: '/products/101' },
        { recordId: 2, supplyType: 'material', itemCode: 'INV-MAG-0045', itemName: 'N52 磁吸组件', relatedProduct: '超星 3.0 iPhone18 黑色', unitPrice: 3.6, currency: 'CNY', lastDeliveryDate: '2026-06-03', status: 'reserved', targetPath: '/products/102' }
      ],
      relatedProjects: [
        { projectCode: 'PRJ-SC30-01', projectName: '超星 3.0 新产品线', roleSummary: 'TPU 主材 + 磁吸件供方', stage: 'BOM 资料确认', targetPath: '/products/101' },
        { projectCode: 'PRJ-SC30-IP18', projectName: '超星 3.0 iPhone18 黑色扩展', roleSummary: '替代料确认', stage: '样品验证', targetPath: '/products/102' }
      ],
      qualificationFiles: [
        { fileName: 'RoHS_2026.pdf', fileType: 'RoHS', validUntil: '2027-03-31', statusLabel: '有效' },
        { fileName: 'MSDS_TPU_85A.pdf', fileType: 'MSDS', validUntil: '2026-12-31', statusLabel: '有效' }
      ]
    },
    {
      supplierId: 202,
      supplierCode: 'SUP-SZ-BOARD-B',
      supplierName: '深圳板材 B',
      shortName: '板材B',
      contactPerson: '陈小姐',
      contactPhone: '13800110002',
      contactEmail: 'chen@board-b.com',
      supplyCategories: ['板材', '包材'],
      region: '深圳',
      status: 'active',
      updatedAt: '2026-06-07T18:10:00+08:00',
      cooperationLevel: '重点合作',
      paymentTerm: '月结 30 天',
      deliveryRisk: 'high',
      supplyRecords: [
        { recordId: 3, supplyType: 'packaging', itemCode: 'INV-PACK-0102', itemName: '渠道彩盒', relatedProduct: '亮甲 3.0 iPhone18 粉色', unitPrice: 1.4, currency: 'CNY', lastDeliveryDate: '2026-05-26', status: 'available', targetPath: '/products/103' },
        { recordId: 4, supplyType: 'material', itemCode: 'INV-BOARD-0091', itemName: 'PC 背板', relatedProduct: '超星 3.0 iPhone18 黑色', unitPrice: 6.8, currency: 'CNY', lastDeliveryDate: '2026-06-02', status: 'reserved', targetPath: '/products/102' }
      ],
      relatedProjects: [
        { projectCode: 'PRJ-LJ30-US', projectName: '亮甲 3.0 北美渠道版', roleSummary: '包装板材 / 彩盒供方', stage: '已发布', targetPath: '/products/103' }
      ],
      qualificationFiles: [
        { fileName: 'REACH_2026.pdf', fileType: 'REACH', validUntil: '2026-10-15', statusLabel: '即将到期' },
        { fileName: '包装材质检测.pdf', fileType: '检测报告', validUntil: '2026-11-30', statusLabel: '有效' }
      ]
    },
    {
      supplierId: 203,
      supplierCode: 'SUP-DG-MOLD-C',
      supplierName: '东莞模具 C',
      shortName: '模具C',
      contactPerson: '王师傅',
      contactPhone: '13800110003',
      contactEmail: 'wang@mold-c.com',
      supplyCategories: ['模具', '治具'],
      region: '东莞',
      status: 'draft',
      updatedAt: '2026-06-06T14:00:00+08:00',
      cooperationLevel: '待评估',
      paymentTerm: '预付 30%',
      deliveryRisk: 'medium',
      supplyRecords: [
        { recordId: 5, supplyType: 'tooling', itemCode: 'INV-MOLD-0201', itemName: '超星 3.0 注塑模', relatedProduct: '超星 3.0', unitPrice: 18000, currency: 'CNY', lastDeliveryDate: '2026-05-18', status: 'in_use', targetPath: '/products/101' }
      ],
      relatedProjects: [
        { projectCode: 'PRJ-SC30-MOLD', projectName: '超星 3.0 开模试制', roleSummary: '注塑模 / 治具制作', stage: '打样中', targetPath: '/products/101' }
      ],
      qualificationFiles: [
        { fileName: '营业执照.pdf', fileType: '基础资质', validUntil: '2028-01-01', statusLabel: '有效' },
        { fileName: 'RoHS_缺失', fileType: 'RoHS', validUntil: '--', statusLabel: '缺失' }
      ]
    }
  ],
  risks: [
    { title: 'PC 背板交期不稳定', level: 'high', owner: '采购', action: '准备第二供方并确认本周到料', targetPath: '/suppliers' },
    { title: '模具供应商资质未补齐', level: 'medium', owner: '采购 / 品质', action: '补齐合规文件后再转正式合作', targetPath: '/suppliers' },
    { title: '黑色 TPU 报价待回签', level: 'medium', owner: '采购', action: '锁定价格后同步 BOM 成本', targetPath: '/costs' }
  ]
}

export const mockUsers: UserOption[] = [
  { userId: 1, userName: '张敏', roleName: '项目经理', department: '项目部' },
  { userId: 2, userName: '刘浩', roleName: '工程', department: '工程部' },
  { userId: 3, userName: '王总', roleName: '管理层', department: '管理层' },
  { userId: 4, userName: '赵越', roleName: '超级管理员', department: '信息部' }
]

export const mockAccounts: Array<{ username: string; password: string; profile: UserProfile }> = [
  { username: 'pm', password: '123456', profile: { userId: 1, userName: '张敏', roleName: '项目经理', department: '项目部' } },
  { username: 'engineer', password: '123456', profile: { userId: 2, userName: '刘浩', roleName: '工程', department: '工程部' } },
  { username: 'manager', password: '123456', profile: { userId: 3, userName: '王总', roleName: '管理层', department: '管理层' } },
  { username: 'admin', password: '123456', profile: { userId: 4, userName: '赵越', roleName: '超级管理员', department: '信息部' } }
]

export const sidebarMenus: MenuGroup[] = [
  {
    title: '工作台',
    items: [{ path: '/dashboard', title: '我的工作台', icon: 'Odometer', permission: 'dashboard:view' }]
  },
  {
    title: '业务管理',
    items: [
      { path: '/products', title: '产品管理', icon: 'Grid', permission: 'product:view' },
      { path: '/sku-view', title: 'SKU 视图', icon: 'Tickets', permission: 'product:view' },
      { path: '/bom', title: 'BOM 资料', icon: 'List', permission: 'product:view' },
      { path: '/projects', title: '项目管理', icon: 'Management', permission: 'project:view' },
      { path: '/orders', title: '需求订单', icon: 'Document', permission: 'order:view' },
      { path: '/production-orders', title: '生产执行', icon: 'Setting', permission: 'production-order:view' },
      { path: '/processes', title: '工艺路线', icon: 'Connection', permission: 'process:view' },
      { path: '/inventories', title: '物料库存', icon: 'Box', permission: 'inventory:view' },
      { path: '/files', title: '文件中心', icon: 'FolderOpened', permission: 'product:view' },
      { path: '/suppliers', title: '供应商管理', icon: 'Van', permission: 'supplier:view' },
      { path: '/quality', title: '质量管理', icon: 'CircleCheck', permission: 'quality:view' }
    ]
  },
  {
    title: '协同中心',
    items: [{ path: '/approval-tasks', title: '审批中心', icon: 'Checked', permission: 'approval:view' }]
  },
  {
    title: '系统管理',
    items: [
      { path: '/system/users', title: '用户管理', icon: 'Avatar', permission: 'admin:user' },
      { path: '/system/roles', title: '角色管理', icon: 'Key', permission: 'admin:role' },
      { path: '/system/fields', title: '字段管理', icon: 'SetUp', permission: 'admin:field' },
      { path: '/system/operation-log', title: '操作日志', icon: 'Tickets', permission: 'admin:log' },
      { path: '/system/import', title: '数据导入', icon: 'Upload', permission: 'admin:import' }
    ]
  }
]

const commonPermissions = [
  'dashboard:view',
  'product:view',
  'customer:view',
  'order:view',
  'project:view',
  'production-order:view',
  'process:view',
  'inventory:view',
  'supplier:view',
  'workstation:view',
  'quality:view',
  'cost:view',
  'report:view',
  'approval:view'
]

export const rolePermissions: Record<string, string[]> = {
  项目经理: [
    ...commonPermissions,
    'product:create',
    'product:edit',
    'product:publish',
    'customer:create',
    'customer:edit',
    'order:create',
    'production-order:create'
  ],
  工程: [...commonPermissions, 'product:create', 'product:edit', 'process:create', 'process:edit'],
  管理层: [...commonPermissions, 'product:publish'],
  超级管理员: [
    ...commonPermissions,
    'product:create',
    'product:edit',
    'product:publish',
    'product:freeze',
    'customer:create',
    'customer:edit',
    'order:create',
    'order:edit',
    'project:create',
    'project:edit',
    'production-order:create',
    'process:create',
    'process:edit',
    'inventory:create',
    'inventory:edit',
    'supplier:create',
    'supplier:edit',
    'workstation:create',
    'workstation:edit',
    'quality:create',
    'quality:edit',
    'admin:user',
    'admin:role',
    'admin:field',
    'admin:log',
    'admin:import'
  ],
  销售: ['dashboard:view', 'product:view', 'customer:view', 'customer:create', 'customer:edit', 'order:view', 'order:create', 'project:view', 'approval:view'],
  采购: ['dashboard:view', 'product:view', 'customer:view', 'order:view', 'inventory:view', 'inventory:create', 'inventory:edit', 'supplier:view', 'supplier:create', 'supplier:edit', 'cost:view', 'approval:view'],
  品质: ['dashboard:view', 'product:view', 'customer:view', 'order:view', 'project:view', 'production-order:view', 'quality:view', 'quality:create', 'quality:edit', 'approval:view'],
  生产: ['dashboard:view', 'product:view', 'customer:view', 'project:view', 'production-order:view', 'process:view', 'workstation:view', 'approval:view'],
  财务: ['dashboard:view', 'product:view', 'cost:view', 'report:view', 'approval:view']
}
