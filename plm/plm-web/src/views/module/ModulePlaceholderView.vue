<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import FixedTableViewport from '@/components/FixedTableViewport/index.vue'
import PageContainer from '@/components/PageContainer/index.vue'
import { normalizeLegacyProductTarget } from '@/utils/projectRoute'

type ModuleKey =
  | 'bom'
  | 'file'
  | 'order'
  | 'project'
  | 'production-order'
  | 'process'
  | 'inventory'
  | 'supplier'
  | 'workstation'
  | 'quality'
  | 'cost'
  | 'report'
  | 'system-user'
  | 'system-role'
  | 'system-dict'
  | 'system-import'

interface MetricItem {
  label: string
  value: string
  hint: string
  targetPath: string
}

interface RecordItem {
  code: string
  name: string
  object: string
  status: string
  owner: string
  nextAction: string
  targetPath: string
}

interface StageItem {
  stage: string
  owner: string
  dueDate: string
  status: '已完成' | '进行中' | '有风险' | '待开始'
  targetPath: string
}

interface RiskItem {
  title: string
  level: '高' | '中' | '低'
  owner: string
  action: string
  targetPath: string
}

interface ModuleConfig {
  title: string
  summary: string
  objectScope: string
  metrics: MetricItem[]
  records: RecordItem[]
  stages: StageItem[]
  risks: RiskItem[]
  checks: string[]
}

const route = useRoute()
const router = useRouter()

const newProductStages: StageItem[] = [
  { stage: '客户/市场需求', owner: '销售 / 项目经理', dueDate: '06-05', status: '已完成', targetPath: '/orders' },
  { stage: '新产品线立项', owner: '项目经理 / 管理层', dueDate: '06-06', status: '已完成', targetPath: '/approval-tasks' },
  { stage: 'Product 建档', owner: '工程', dueDate: '06-07', status: '已完成', targetPath: '/products/101' },
  { stage: '工艺与样品验证', owner: '工程 / 品质', dueDate: '06-10', status: '进行中', targetPath: '/quality' },
  { stage: 'BOM 资料确认', owner: '工程 / 采购', dueDate: '06-12', status: '进行中', targetPath: '/bom' },
  { stage: '文件与质量资料冻结', owner: '工程 / 品质', dueDate: '06-14', status: '有风险', targetPath: '/products?frozen=unfrozen' },
  { stage: 'Product 发布', owner: '工程 / 管理层', dueDate: '06-16', status: '待开始', targetPath: '/products' },
  { stage: '历史追溯', owner: '系统 / 业务团队', dueDate: '06-18', status: '待开始', targetPath: '/reports' }
]

const baseRecords: RecordItem[] = [
  {
    code: 'PRD-SC30-0001',
    name: '超星 3.0 新产品线',
    object: 'Product',
    status: '开发中',
    owner: '张敏',
    nextAction: '完成红样测试并补齐质量资料',
    targetPath: '/products/101'
  },
  {
    code: 'PRD-SC30-IP18-BLK-A',
    name: 'iPhone18 黑色型号扩展',
    object: 'Product / Process',
    status: '进行中',
    owner: '刘浩',
    nextAction: '确认 EBOM、包装 BOM 和替代料',
    targetPath: '/products/102'
  },
  {
    code: 'PRD-LJ30-IP18-PNK-B',
    name: '亮甲 3.0 粉色发布版本',
    object: 'Product / Inventory',
    status: '已发布',
    owner: '赵越',
    nextAction: '查看冻结资料与历史追溯',
    targetPath: '/products/103'
  }
]

function makeDefault(title: string, summary: string, objectScope: string): ModuleConfig {
  return {
    title,
    summary,
    objectScope,
    metrics: [
      { label: '进行中', value: '12', hint: '点击查看相关列表', targetPath: '/products?status=developing' },
      { label: '待处理', value: '5', hint: '需要责任人继续推进', targetPath: '/approval-tasks' },
      { label: '本周到期', value: '8', hint: '含关键流程节点', targetPath: '/projects' },
      { label: '已完成', value: '21', hint: '可查看冻结版本和历史', targetPath: '/reports' }
    ],
    records: baseRecords,
    stages: newProductStages.slice(0, 4),
    risks: [
      {
        title: '资料完整性待确认',
        level: '中',
        owner: '项目经理',
        action: '补齐责任人、下一步动作和节点附件',
        targetPath: '/products'
      }
    ],
    checks: ['状态、责任人、下一步动作清晰可见', '点击统计卡片可进入相关页面', '不新增七个核心对象之外的根对象']
  }
}

const configs: Record<ModuleKey, ModuleConfig> = {
  bom: {
    title: 'BOM 资料',
    summary: 'BOM 作为 Product 的版本化资料和 Inventory 用量明细呈现，不作为独立根对象。',
    objectScope: 'Product 版本资料 + Inventory 用量明细',
    metrics: [
      { label: 'BOM 完整率', value: '86%', hint: '5 个版本待补齐替代料', targetPath: '/products?frozen=unfrozen' },
      { label: '已冻结版本', value: '18', hint: '发布前资料可追溯', targetPath: '/products?frozen=frozen' },
      { label: '替代料待确认', value: '7', hint: '采购需确认价格与交期', targetPath: '/inventories?risk=substitute' },
      { label: '包装 BOM 风险', value: '3', hint: '彩盒 / 标签版本待锁定', targetPath: '/suppliers?category=pack' }
    ],
    records: [
      { code: 'BOM-SC30-A', name: '超星 3.0 基础 EBOM', object: 'Product + Inventory', status: '待补齐', owner: '工程 / 采购', nextAction: '确认磁吸组件替代料', targetPath: '/products/101' },
      { code: 'BOM-SC30-IP18-A', name: 'iPhone18 黑色 MBOM', object: 'Product + Process', status: '待补齐', owner: '刘浩', nextAction: '确认黑色 TPU 单价', targetPath: '/products/102' },
      { code: 'BOM-LJ30-B', name: '亮甲 3.0 包装 BOM', object: 'Product + Inventory', status: '已冻结', owner: '赵越', nextAction: '查看发布版本', targetPath: '/products/103' }
    ],
    stages: newProductStages,
    risks: [
      { title: '黑色 TPU 替代料未确认', level: '中', owner: '采购', action: '补齐供应商报价和交期', targetPath: '/suppliers' },
      { title: '包装标签版本未冻结', level: '中', owner: '工程', action: '确认客户版包装资料', targetPath: '/products/102' }
    ],
    checks: ['EBOM / MBOM / 包装 BOM 分区呈现', '用量、损耗率、替代料、供应来源必须可见', '发布前校验资料完整率和审批状态']
  },
  file: {
    title: '文件中心',
    summary: '文件中心聚合 Product、Process、Quality 相关图纸、SOP、SIP、测试报告与客户确认件，前端以归档与冻结视图呈现。',
    objectScope: 'Product + Process + Quality 资料归档',
    metrics: [
      { label: '待归档文件', value: '12', hint: '图纸、SOP、SIP 与测试报告待补齐', targetPath: '/files' },
      { label: '待冻结版本', value: '5', hint: '发布前需锁定文件版本', targetPath: '/products?frozen=unfrozen' },
      { label: '客户确认件', value: '8', hint: '点击查看对应产品版本', targetPath: '/files' },
      { label: '已归档版本', value: '19', hint: '可追溯历史发布资料', targetPath: '/products?frozen=frozen' }
    ],
    records: [
      { code: 'FILE-SC30-A', name: '超星 3.0 图纸与测试资料', object: 'Product / Quality', status: '待补齐', owner: '工程 / 品质', nextAction: '补齐 SIP 与酒精测试报告', targetPath: '/products/101' },
      { code: 'FILE-SC30-IP18', name: 'iPhone18 黑色包装与 BOM 附件', object: 'Product / Process', status: '待补齐', owner: '刘浩', nextAction: '锁定包装标签与客户确认件', targetPath: '/products/102' },
      { code: 'FILE-LJ30-B', name: '亮甲 3.0 发布归档包', object: 'Product', status: '已冻结', owner: '赵越', nextAction: '查看历史版本追溯', targetPath: '/products/103' }
    ],
    stages: [
      { stage: '图纸归档', owner: '工程', dueDate: '06-08', status: '进行中', targetPath: '/products/101' },
      { stage: 'SOP / SIP 冻结', owner: '工程 / 品质', dueDate: '06-10', status: '有风险', targetPath: '/products?frozen=unfrozen' },
      { stage: '客户确认件挂接', owner: '销售', dueDate: '06-11', status: '待开始', targetPath: '/products/103' },
      { stage: '发布归档', owner: '项目经理', dueDate: '06-14', status: '待开始', targetPath: '/approval-tasks' }
    ],
    risks: [
      { title: 'SOP / SIP 资料未冻结', level: '高', owner: '工程 / 品质', action: '补齐后再提交发布审批', targetPath: '/products?frozen=unfrozen' },
      { title: '客户确认件未挂接版本', level: '中', owner: '销售', action: '将签样确认件绑定到产品版本', targetPath: '/products/103' }
    ],
    checks: ['文件必须绑定到 Product 版本', '冻结前需显示缺失清单与责任人', '点击记录应能回到对应业务对象详情']
  },
  project: {
    title: '项目管理',
    summary: '项目管理是 Product、Order、ProductionOrder、Process 的协同视图，不新增 Project 根对象。',
    objectScope: 'Product + Order + ProductionOrder + Process',
    metrics: [
      { label: '进行中项目', value: '16', hint: '点击查看项目列表', targetPath: '/products?status=developing' },
      { label: '待管理层确认', value: '4', hint: '立项 / 发布等关键节点', targetPath: '/approval-tasks?status=pending' },
      { label: '本周到期节点', value: '9', hint: '含 3 个风险节点', targetPath: '/projects?due=this_week' },
      { label: '延期项目', value: '3', hint: '测试和资料冻结影响排期', targetPath: '/reports?type=delay' }
    ],
    records: baseRecords,
    stages: newProductStages,
    risks: [
      { title: '文件与质量资料冻结延期', level: '高', owner: '工程 / 品质', action: '优先补齐 SOP、SIP 和检验标准', targetPath: '/products?frozen=unfrozen' },
      { title: '图纸版本与 BOM 不一致', level: '高', owner: '工程', action: '复核当前版本资料', targetPath: '/products/102' }
    ],
    checks: ['一项目一档案，但不新增 Project 根对象', '节点必须显示责任人、截止时间、下一步动作', '风险直接跳转到对应业务节点']
  },
  supplier: {
    title: '供应商管理',
    summary: '供应商信息作为 Inventory 的供应侧资料维护，本期供应商不登录系统。',
    objectScope: 'Inventory 供应侧资料 + Cost 权限控制',
    metrics: [
      { label: '合作供应商', value: '28', hint: '物料、包材、模具供应侧', targetPath: '/suppliers?status=active' },
      { label: '待确认报价', value: '6', hint: '成本权限内可查看', targetPath: '/costs' },
      { label: '交期风险', value: '3', hint: '影响打样和资料确认', targetPath: '/suppliers?risk=delivery' },
      { label: '质量资料缺口', value: '4', hint: 'RoHS / REACH / MSDS 待补', targetPath: '/quality?source=supplier' }
    ],
    records: [
      { code: 'SUP-DG-PLASTIC-A', name: '东莞塑胶 A / TPU 原料', object: 'Inventory 供应信息', status: '合作中', owner: '采购-林', nextAction: '确认 6 月价格', targetPath: '/costs' },
      { code: 'SUP-SZ-BOARD-B', name: '深圳板材 B / PC 背板', object: 'Inventory 供应信息', status: '交期风险', owner: '采购-陈', nextAction: '跟进本周到料', targetPath: '/inventories' },
      { code: 'SUP-HZ-MATERIAL-C', name: '惠州材料 C / 镜面片', object: 'Inventory 供应信息', status: '待评估', owner: '采购-林', nextAction: '补齐样品测试资料', targetPath: '/quality' }
    ],
    stages: [
      { stage: '资质维护', owner: '采购', dueDate: '06-05', status: '已完成', targetPath: '/suppliers' },
      { stage: '报价确认', owner: '采购 / 财务', dueDate: '06-06', status: '进行中', targetPath: '/costs' },
      { stage: '样品验证', owner: '品质', dueDate: '06-08', status: '有风险', targetPath: '/quality' },
      { stage: '交期跟进', owner: '采购', dueDate: '06-10', status: '进行中', targetPath: '/inventories' }
    ],
    risks: [{ title: 'PC 背板供应交期不稳', level: '中', owner: '采购', action: '准备第二供应来源', targetPath: '/inventories' }],
    checks: ['供应商不是独立核心对象，只作为 Inventory 供应信息', '供应商本期不登录系统，由内部人员维护', '成本和报价字段按角色权限控制']
  },
  process: {
    title: '工艺管理',
    summary: '使用 Process 管理工艺路线、工序参数、SOP/SIP、检验标准和工程变更动作。',
    objectScope: 'Process + Product + Workstation',
    metrics: [
      { label: '已确认工艺', value: '23', hint: '含注塑、喷涂、贴合、包装', targetPath: '/processes?status=confirmed' },
      { label: '待锁定版本', value: '6', hint: '发布前冻结 SOP/SIP', targetPath: '/processes?status=confirmed' },
      { label: '变更申请', value: '2', hint: '影响 BOM 与质量标准', targetPath: '/approval-tasks?keyword=变更' },
      { label: '关键工序', value: '12', hint: '点击查看工序清单', targetPath: '/processes?view=operations' }
    ],
    records: baseRecords,
    stages: [
      { stage: '注塑', owner: '工艺', dueDate: '06-05', status: '已完成', targetPath: '/workstations' },
      { stage: 'CNC / 打磨', owner: '工艺', dueDate: '06-06', status: '已完成', targetPath: '/processes' },
      { stage: '清胶处理', owner: '生产', dueDate: '06-07', status: '进行中', targetPath: '/production-orders' },
      { stage: '沾磁铁', owner: '工艺', dueDate: '06-09', status: '有风险', targetPath: '/quality' }
    ],
    risks: [{ title: '磁吸力参数未达标', level: '中', owner: '工艺 / 品质', action: '复核贴磁压力和固化时间', targetPath: '/quality' }],
    checks: ['工艺版本锁定后只能通过变更流程调整', 'SOP/SIP 与 Product、Process 绑定', 'BOM 和工艺变更要提示影响范围']
  },
  quality: {
    title: '质量管理',
    summary: '统一管理产品检验标准、样品测试、试产检验、不良问题、质量闭环和合规资料。',
    objectScope: 'Product + ProductionOrder + Process',
    metrics: [
      { label: '待执行测试', value: '9', hint: '跌落、耐磨、高低温等', targetPath: '/quality?status=pending' },
      { label: '本周关闭异常', value: '4', hint: 'CAPA 已闭环', targetPath: '/quality?closed=this_week' },
      { label: '待审批放行', value: '3', hint: '红样 / 黄样 / 量产资料', targetPath: '/approval-tasks?status=pending' },
      { label: '合规资料缺口', value: '5', hint: 'RoHS / REACH / MSDS', targetPath: '/quality?type=compliance' }
    ],
    records: baseRecords,
    stages: [
      { stage: '跌落测试', owner: '品质', dueDate: '06-05', status: '进行中', targetPath: '/products/101' },
      { stage: '耐磨测试', owner: '品质', dueDate: '06-06', status: '待开始', targetPath: '/quality' },
      { stage: '酒精测试', owner: '品质', dueDate: '06-08', status: '有风险', targetPath: '/products/101' },
      { stage: '磁吸力测试', owner: '品质', dueDate: '06-10', status: '进行中', targetPath: '/products/101' }
    ],
    risks: [{ title: '酒精测试未完成', level: '高', owner: '品质', action: '补录测试结果后再放行', targetPath: '/products/101' }],
    checks: ['质量资料绑定 Product、Process 或 ProductionOrder', '不良记录需包含图片、原因、责任人和处理措施', '红样、黄样和量产资料放行必须留痕']
  },
  order: makeDefault('订单 / 需求', '使用 Order 承载客户需求、市场需求、样品需求、报价需求和内部开发需求。', 'Order + Customer + Product'),
  'production-order': makeDefault('生产执行', '使用 ProductionOrder 表达打样、试产、量产准备、开模试制和返工试制。', 'ProductionOrder + Workstation + Inventory'),
  inventory: makeDefault('物料 / 模具', '使用 Inventory 统一管理物料、半成品、成品、包装材料、模具治具和资料占用状态。', 'Inventory + Product + Workstation'),
  workstation: makeDefault('机台 / 工位', '使用 Workstation 管理机台、工位、产线、模具所在设备和工序执行位置。', 'Workstation + ProductionOrder + Process'),
  cost: makeDefault('成本 / 报价', '基于 Product、Inventory、Process 和 Order 管理成本与报价审核。', 'Product + Inventory + Process + Order'),
  report: makeDefault('报表中心', '汇总新品进度、延期、打样、BOM 完整率、变更、模具、质量、成本和生命周期状态。', '七个核心对象的统计视图'),
  'system-user': makeDefault('用户管理', '统一维护内部用户、部门、角色和启停状态。', '系统配置'),
  'system-role': makeDefault('角色管理', '承载菜单权限、按钮权限、字段权限和数据权限配置。', '系统配置'),
  'system-dict': makeDefault('字典管理', '维护状态、来源、工艺分类、物料类型、测试项目等基础枚举。', '系统配置'),
  'system-import': makeDefault('数据导入', '承载主数据模板、校验反馈和导入记录查询。', '系统配置')
}

const moduleKey = computed(() => (route.meta.moduleKey || 'order') as ModuleKey)
const current = computed(() => configs[moduleKey.value])

function openTarget(path: string) {
  router.push(normalizeLegacyProductTarget(path))
}

function tagType(text: string) {
  if (['高', '风险', '异常'].some((item) => text.includes(item))) return 'danger'
  if (['中', '评审', '待', '处理中'].some((item) => text.includes(item))) return 'warning'
  if (['已', '完成', '通过', '冻结', '发布'].some((item) => text.includes(item))) return 'success'
  return 'info'
}
</script>

<template>
  <PageContainer :title="current.title" :description="current.summary">
    <section class="metric-grid">
      <button v-for="metric in current.metrics" :key="metric.label" class="metric-card module-button" type="button" @click="openTarget(metric.targetPath)">
        <p class="metric-card__label">{{ metric.label }}</p>
        <p class="metric-card__value">{{ metric.value }}</p>
        <div class="module-card-footer">
          <span>{{ metric.hint }}</span>
          <el-icon><ArrowRight /></el-icon>
        </div>
      </button>
    </section>

    <section class="page-panel">
      <div class="toolbar-row">
        <div>
          <h3 class="section-title">业务承载范围</h3>
          <p class="page-panel-desc">{{ current.objectScope }}</p>
        </div>
        <el-tag type="info" effect="light">接口未接入</el-tag>
      </div>
    </section>

    <section class="page-panel">
      <h3 class="section-title">阶段节点</h3>
      <div class="stage-grid">
        <button v-for="stage in current.stages" :key="`${stage.stage}-${stage.dueDate}`" class="stage-item module-button" type="button" @click="openTarget(stage.targetPath)">
          <div class="toolbar-row">
            <strong>{{ stage.stage }}</strong>
            <el-tag :type="tagType(stage.status)" effect="light">{{ stage.status }}</el-tag>
          </div>
          <p class="subtle-text">{{ stage.owner }}</p>
          <div class="module-card-footer">
            <span>截止 {{ stage.dueDate }}</span>
            <el-icon><ArrowRight /></el-icon>
          </div>
        </button>
      </div>
    </section>

    <section class="split-grid">
      <article class="page-panel">
        <h3 class="section-title">业务列表</h3>
        <FixedTableViewport v-slot="{ tableHeight }" :refresh-key="current.records">
        <el-table :data="current.records" :height="tableHeight" border stripe @row-click="(row: RecordItem) => openTarget(row.targetPath)">
          <el-table-column prop="code" label="编码" min-width="180" />
          <el-table-column prop="name" label="名称" min-width="220" />
          <el-table-column prop="object" label="承载对象" min-width="150" />
          <el-table-column prop="status" label="状态" width="120">
            <template #default="{ row }">
              <el-tag :type="tagType(row.status)" effect="light">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="owner" label="责任人" width="130" />
          <el-table-column prop="nextAction" label="下一步动作" min-width="220" />
        </el-table>
        </FixedTableViewport>
      </article>

      <article class="page-panel">
        <h3 class="section-title">风险提醒</h3>
        <button v-for="risk in current.risks" :key="risk.title" class="risk-item module-button" type="button" @click="openTarget(risk.targetPath)">
          <div class="toolbar-row">
            <strong>{{ risk.title }}</strong>
            <el-tag :type="risk.level === '高' ? 'danger' : risk.level === '中' ? 'warning' : 'info'" effect="light">{{ risk.level }}</el-tag>
          </div>
          <p class="page-panel-desc">责任人：{{ risk.owner }}</p>
          <div class="module-card-footer">
            <span>{{ risk.action }}</span>
            <el-icon><ArrowRight /></el-icon>
          </div>
        </button>

        <h3 class="section-title checklist-title">需求校验点</h3>
        <button v-for="item in current.checks" :key="item" class="check-item module-button" type="button">
          <span>{{ item }}</span>
        </button>
      </article>
    </section>
  </PageContainer>
</template>

<style scoped>
.module-button {
  width: 100%;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.16s ease, box-shadow 0.16s ease, transform 0.16s ease;
}

.module-button:hover {
  border-color: var(--plm-color-primary);
  box-shadow: var(--plm-shadow-md);
  transform: translateY(-1px);
}

.module-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 10px;
  color: var(--plm-color-primary);
  font-size: var(--plm-font-size-sm);
}

.stage-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--plm-space-3);
}

.stage-item,
.risk-item,
.check-item {
  padding: 12px;
  border: 1px solid var(--plm-color-border-light);
  border-radius: var(--plm-radius-base);
  background: #fff;
  color: inherit;
}

.stage-item p,
.risk-item p {
  margin: 8px 0 0;
}

.risk-item,
.check-item {
  margin-bottom: 10px;
}

.checklist-title {
  margin-top: var(--plm-space-5);
}

@media (max-width: 1200px) {
  .stage-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .stage-grid {
    grid-template-columns: 1fr;
  }
}
</style>
