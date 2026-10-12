# PLM 新产品线与新型号线 Playwright 端到端巡检问题修复方案

日期：2026-08-11  
状态：方案沉淀，暂不修改业务代码  
来源：`2026-08-11-PLM新产品线与新型号线Playwright端到端巡检问题沉淀.md`

## 1. 背景

本方案基于端到端巡检结果，归并两条测试数据在工作台、项目中心、时间轴、BOM、工艺路线、发布门禁和钉钉回传上的问题，形成可落地的修复计划。

本次只沉淀方案，不改业务代码。执行前已阅读：

- `D:\work\资料\PLM\docs\文件沉淀\开发提示词.md`

## 2. 目标

1. 新产品线、 新型号线从工作台到完成态的体验一致。
2. 完成后时间轴自动收口为 `completed`，Product 自动进入 `released`。
3. 钉钉完成后回传有明确出站记录，不再只在后端 warn。
4. 项目中心详情页与 Dashboard 的状态、入口、门禁保持同步。
5. 颜色、材质、负责人、成品编码等基础信息可读、可追踪、可回归。
6. 不新增根对象，不改状态机，不引入外部系统正式集成。

## 3. 巡检结论归并

### P0

- 新型号线完成运模后没有生成 `model_variant_mold_transfer_completed` outbound 记录。
- 这意味着“完成后钉钉代同意”链路没有形成可追踪结果。

### P1

- 新型号 released 后旧的 `tab=in_progress&productId=19249` 详情路由不稳定。
- 新型号完成后工作台弹窗状态曾短暂显示“开发中”，阶段标题也不够准确。
- Dashboard 只有“敲定投产工序”，没有单独的颜色确认入口。
- 新产品线基础信息颜色 / 材质展示为 JSON 字符串，可读性差。
- 新型号 `colorCode=02 / color=Negro`，但 `finishedProductCode` 仍带原始尾码，存在编码一致性疑点。

### P2

- 项目负责人 `ownerUserName=null`，工作台和详情都不够完整。
- 静态资源仍有 404 控制台噪音。
- 发布门禁已可通过，但页面仍保留风险 warning，需要在文案上区分“提醒”和“阻塞”。

## 4. 修复范围

### 4.1 前端

- `plm-web/src/views/dashboard/DashboardView.vue`
- `plm-web/src/views/project/ProjectCenterView.vue`
- `plm-web/src/views/project/components/ProjectReleaseGatePanel.vue`
- `plm-web/src/views/project/components/ProjectProcessRoutePanel.vue`
- `plm-web/src/views/project/components/ProductionConfirmationDialog.vue`
- `plm-web/src/views/project/__tests__/project-m5-release-gate-panel.spec.ts`
- `plm-web/src/views/project/__tests__/project-m4-panels.spec.ts`
- `plm-web/src/views/dashboard/__tests__/DashboardView.spec.ts`

### 4.2 后端

- `plm-server/src/main/java/com/yuewei/plm/module/project/service/impl/TimelineActionServiceImpl.java`
- `plm-server/src/main/java/com/yuewei/plm/module/integration/dingtalk/service/DingTalkProjectCompletionReturnService.java`
- `plm-server/src/main/java/com/yuewei/plm/module/project/service/impl/ProjectServiceImpl.java`
- `plm-server/src/main/java/com/yuewei/plm/module/process/service/impl/ProcessRouteServiceImpl.java`
- `plm-server/src/main/java/com/yuewei/plm/module/process/service/ProcessRouteInheritanceService.java`
- `plm-server/src/main/java/com/yuewei/plm/module/project/vo/ProjectDetailVO.java`
- `plm-server/src/main/java/com/yuewei/plm/module/project/vo/ProjectSummaryVO.java`
- `plm-server/src/main/java/com/yuewei/plm/module/process/vo/ProcessOperationVO.java`

## 5. 详细修复方案

### 5.1 完成后钉钉回传要可观测

#### 目标效果

- 新型号运模完成后，数据库中能稳定看到 `integration_type=model_variant_mold_transfer_completed` 的 outbound 记录。
- 如果 taskId 缺失、自动审批人未配置、外部 endpoint 不可用，都要明确写入失败记录和操作日志。
- 前端详情页可看到“完成回传成功 / 失败 / 待补齐”的状态，不只靠后端 warn。

#### 后端改法

当前入口：

```java
private void triggerDingTalkCompletionReturn(Product product, TimelineNodeDefinition currentNode, String operator) {
    if (dingTalkProjectCompletionReturnService == null) {
        return;
    }
    Runnable task = () -> {
        try {
            dingTalkProjectCompletionReturnService.handleProjectCompleted(product, currentNode, operator);
        } catch (Exception ex) {
            log.warn(
                "DingTalk project completion return failed after PLM timeline completion, projectId={}, nodeKey={}",
                product.getProductId(),
                currentNode.nodeCode(),
                ex
            );
        }
    };
    if (TransactionSynchronizationManager.isSynchronizationActive()) {
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                task.run();
            }
        });
        return;
    }
    task.run();
}
```

建议增强为：

```java
private void triggerDingTalkCompletionReturn(Product product, TimelineNodeDefinition currentNode, String operator) {
    if (dingTalkProjectCompletionReturnService == null) {
        return;
    }
    Runnable task = () -> {
        try {
            DingTalkOutboundTriggerResultVO result =
                dingTalkProjectCompletionReturnService.handleProjectCompleted(product, currentNode, operator);
            writeCompletionReturnLog(product, currentNode, result);
        } catch (Exception ex) {
            writeCompletionReturnFailureLog(product, currentNode, ex.getMessage());
            log.warn("DingTalk project completion return failed after PLM timeline completion, projectId={}, nodeKey={}",
                product.getProductId(), currentNode.nodeCode(), ex);
        }
    };
    if (TransactionSynchronizationManager.isSynchronizationActive()) {
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                task.run();
            }
        });
        return;
    }
    task.run();
}
```

`DingTalkProjectCompletionReturnService` 里建议补强：

```java
if (!StringUtils.hasText(payload.get("taskId"))) {
    errorMessage = "钉钉等待节点 taskId 未保存，且兜底查询未返回 taskId，无法自动代同意";
}

IntegrationRecord record = saveOutbound(...);
operationLogService.logSuccess(
    OperationLogCreateCommand.builder()
        .action(OperationActionConstants.DINGTALK_PROJECT_COMPLETION_RETURN)
        .businessType("PRODUCT")
        .businessId(String.valueOf(product.getProductId()))
        .businessCode(product.getProductCode())
        .businessName(product.getProductName())
        .detailJson("{\"status\":\"" + record.getProcessingStatus() + "\",\"nodeKey\":\"" + node.nodeCode() + "\"}")
        .build()
);
```

#### 前端改法

在项目详情页增加“完成回传”状态展示，复用已有项目状态卡，不新增对象：

```vue
<div class="info-card">
  <span class="subtle-text">钉钉完成回传</span>
  <strong>{{ completionReturnStatusLabel }}</strong>
</div>
```

对应数据来源建议走现有项目详情接口扩展字段，不改业务对象。

---

### 5.2 新型号 released 后详情路由要稳定

#### 目标效果

- 完成后的新型号，即使从历史链接进入，也能打开项目详情。
- 不再依赖 `tab=in_progress` 才能查看已发布项目。

#### 前端改法

`plm-web/src/views/project/ProjectCenterView.vue`

建议在打开详情时对 `released` 项目自动纠正 tab：

```ts
function normalizeProjectDetailRoute(target: ProjectDetailTarget) {
  if (target.status === 'released' || target.status === 'archived') {
    return {
      ...route.query,
      tab: 'all',
      productId: String(target.productId)
    }
  }
  return route.query
}
```

进入详情时不要硬绑定 `tab=in_progress`。

#### 后端改法

不需要改状态机，只需确保 `GET /api/v1/projects/{projectId}` 对 released 项目仍可稳定返回详情。

---

### 5.3 Dashboard 完成后要及时刷新状态

#### 目标效果

- 新型号最后一步完成后，工作台弹窗立即显示 `released / 已完成`。
- 阶段标题不再停留在“选择订单类型”或旧步骤名。

#### 前端改法

`plm-web/src/views/dashboard/DashboardView.vue`

建议在确认成功后重新拉取当前项目详情和时间轴，并重新计算弹窗文案：

```ts
async function refreshActiveProgressProject() {
  if (!activeProgressProject.value) return
  activeProgressProject.value = null
  await loadInProgressProjects()
}
```

更稳妥的做法是重新拉 `project detail + timeline`，而不是只改本地对象：

```ts
async function handleRequirementFormConfirmed() {
  if (!activeProgressProject.value) return
  await loadActiveProgressTimeline(activeProgressProject.value.productId)
  await loadInProgressProjects()
}
```

最后节点确认成功后建议把：

- `activeProgressProject.status`
- `activeProgressProject.currentStage`
- `activeProgressProject.currentStepNo`

一起刷新。

---

### 5.4 投产颜色入口要明确

#### 目标效果

- 用户能清楚看到“确认投产工序”和“确认投产颜色”是两个动作。
- Dashboard 不再只剩一个“敲定投产工序”按钮让颜色确认隐式发生。

#### 前端改法

`plm-web/src/views/dashboard/DashboardView.vue`

建议在投产决策节点增加显式入口：

```vue
<el-button
  v-if="node.nodeKey === 'PRODUCT_LINE_PRODUCTION_DECISION_STEP' || node.nodeKey === 'MODEL_VARIANT_MOLD_TRANSFER'"
  size="small"
  type="primary"
  plain
  @click="openProductionConfirmation('colors')"
>
  确认投产颜色
</el-button>
```

`ProductionConfirmationDialog.vue` 继续使用现有 `mode='colors'`，避免新建逻辑。

#### 后端改法

后端不新增接口，只沿用现有：

- `GET /api/v1/projects/{projectId}/production-confirmation`
- `POST /api/v1/projects/{projectId}/production-confirmation/routes`

---

### 5.5 颜色 / 材质 / 负责人要可读

#### 目标效果

- 新产品线基础信息里的数组字段不再显示原始 JSON。
- 新型号的颜色编码、颜色名称能稳定展示。
- 负责人空值时展示“待分配”，不要只显示 `--`。

#### 前端改法

`plm-web/src/views/project/ProjectCenterView.vue`

建议加一个统一转换函数：

```ts
function formatScalarOrArray(value: unknown) {
  if (Array.isArray(value)) return value.join('、')
  if (typeof value === 'string' && value.trim().startsWith('[')) {
    try {
      const parsed = JSON.parse(value)
      if (Array.isArray(parsed)) return parsed.join('、')
    } catch {}
  }
  return value || '--'
}
```

基础信息展示改成：

```vue
<strong>{{ formatScalarOrArray(detailTarget.color) }}</strong>
```

负责人建议改为：

```vue
<strong>{{ detailTarget.ownerUserName || '待分配' }}</strong>
```

后端 `ProjectDetailVO`、`ProjectSummaryVO` 不需要新增根对象，只要保持字段口径清晰即可。

---

### 5.6 成品编码一致性要收口

#### 目标效果

- 新型号颜色变化后，成品编码、颜色编码、基础工序编码不会互相打架。
- 页面上能明确看出 `colorCode=02`、`color=Negro`、`finishedProductCode=...` 的关系。

#### 后端建议

保留现有生成规则，不做硬改；但增加显式校验和说明，避免前端误判。

`plm-server/src/main/java/com/yuewei/plm/module/process/service/ProcessRouteInheritanceService.java`

建议在继承时把生成上下文完整写入：

```java
params.put("businessOperationCode", businessOperationCode);
params.put("operationCraftCode", context.operationCraftCode());
params.put("phoneModelCode", context.phoneModelCode());
params.put("colorCode", context.colorCode());
params.put("generatedFinishedProductCode", generatedFinishedProductCode);
```

这样前端或调试页就能完整回显，不依赖推断。

#### 前端建议

`ProjectProcessRoutePanel.vue` 底部核对表建议拆开显示：

```vue
<el-table-column prop="businessOperationCode" label="产品工序编码" min-width="180" />
<el-table-column prop="operationCraftCode" label="基础工序编码" min-width="140" />
```

这点与上一份编码一致性修复方案保持一致，避免再次混淆。

---

### 5.7 发布门禁与历史路线要区分提醒和阻塞

#### 目标效果

- `passed=true` 时明确是“可发布，但仍有提醒项”。
- 缺少资料不再表现为强阻塞，但保留 warning。

#### 前端改法

`ProjectReleaseGatePanel.vue`

建议把标题文案调整成：

```vue
<p class="page-panel-desc">资料缺口会提示确认；仅在硬门禁不通过时阻塞发布。</p>
```

按钮文案保持现有，但在 warning 区域加“非阻塞提醒”标识。

---

### 5.8 静态 404 要清理

#### 目标效果

- Playwright 控制台不再有无关 404 噪音。
- 真实错误更容易被发现。

#### 修复方向

- 检查 `plm-web/public`、`index.html`、`vite` 产物和 favicon 引用。
- 找不到资源时，不要用旧路径硬撑。

---

## 6. 修改文件清单

### 前端

- `plm-web/src/views/dashboard/DashboardView.vue`
- `plm-web/src/views/project/ProjectCenterView.vue`
- `plm-web/src/views/project/components/ProjectReleaseGatePanel.vue`
- `plm-web/src/views/project/components/ProductionConfirmationDialog.vue`
- `plm-web/src/views/project/components/ProjectProcessRoutePanel.vue`
- `plm-web/src/views/dashboard/__tests__/DashboardView.spec.ts`
- `plm-web/src/views/project/__tests__/project-m5-release-gate-panel.spec.ts`
- `plm-web/src/views/project/__tests__/project-m4-panels.spec.ts`

### 后端

- `plm-server/src/main/java/com/yuewei/plm/module/project/service/impl/TimelineActionServiceImpl.java`
- `plm-server/src/main/java/com/yuewei/plm/module/integration/dingtalk/service/DingTalkProjectCompletionReturnService.java`
- `plm-server/src/main/java/com/yuewei/plm/module/project/service/impl/ProjectServiceImpl.java`
- `plm-server/src/main/java/com/yuewei/plm/module/process/service/impl/ProcessRouteServiceImpl.java`
- `plm-server/src/main/java/com/yuewei/plm/module/process/service/ProcessRouteInheritanceService.java`

## 7. 建议验收方式

1. 用 Playwright 再跑一遍两条线。
2. 确认工作台完成后卡片消失。
3. 确认新型号最终状态为 `released`。
4. 确认钉钉 outbound 有成功或失败记录，不再是无感 warn。
5. 确认基础信息颜色、材质、负责人展示可读。
6. 确认工艺路线核对表里“产品工序编码 / 基础工序编码”分开展示。

## 8. 本次沉淀说明

本次只新增方案文档，未修改业务代码。

新增文档：

- `docs/文件沉淀/2026-08-11-PLM新产品线与新型号线Playwright端到端巡检问题修复方案.md`

引用文档：

- `docs/文件沉淀/2026-08-11-PLM新产品线与新型号线Playwright端到端巡检问题沉淀.md`
- `D:\work\资料\PLM\docs\文件沉淀\开发提示词.md`

## 9. 2026-08-11 实施记录

本次已按方案落地代码修改，保持核心对象仍为 `Product / Process` 等既有对象，不新增根对象，不扩展外部系统正式集成范围。

### 9.1 修改文件

后端：

- `plm-server/src/main/java/com/yuewei/plm/module/integration/dingtalk/service/DingTalkProjectCompletionReturnService.java`
- `plm-server/src/test/java/com/yuewei/plm/module/integration/dingtalk/DingTalkProjectCompletionReturnServiceTest.java`

前端：

- `plm-web/src/views/dashboard/DashboardView.vue`
- `plm-web/src/views/project/ProjectCenterView.vue`
- `plm-web/src/views/project/components/ProjectProcessRoutePanel.vue`
- `plm-web/src/views/project/components/ProjectReleaseGatePanel.vue`
- `plm-web/src/views/dashboard/__tests__/DashboardView.spec.ts`
- `plm-web/src/views/project/__tests__/project-m4-panels.spec.ts`
- `plm-web/src/views/project/__tests__/project-m5-release-gate-panel.spec.ts`
- `plm-web/index.html`
- `plm-web/public/favicon.svg`

测试辅助：

- `.codex_tmp/playwright-dashboard-color-route-check.cjs`

### 9.2 修改逻辑

1. 钉钉完成回传可观测：新产品线 / 新型号线完成后，即使找不到对应钉钉 inbound 记录，也会写入 `outbound` 失败记录，错误信息明确为缺少入站记录；已有成功 outbound 仍保持幂等命中，不重复触发。
2. Dashboard 完成态刷新：节点确认后重新拉取时间轴和项目详情，完成态立即同步 `released`、当前阶段、当前步骤和完成率，避免弹窗短暂停留旧状态。
3. Dashboard 投产颜色入口：在新产品线投产决策、新型号线运模节点增加“确认投产颜色”按钮，使用现有 `ProductionConfirmationDialog` 的 `colors` 模式，不新增接口。
4. released 详情旧链接兼容：项目中心打开 released / archived 项目详情时自动切换到归档视图；旧 `tab=in_progress&productId=...` 链接仍能打开详情。
5. 基础信息可读性：项目详情颜色、材质支持 JSON 数组字符串格式化为 `、` 分隔文本；负责人空值统一显示“待分配”。
6. 工艺路线核对表：节点核对表拆分展示“产品工序编码”和“基础工序编码”；录入提示与校验文案改为基础工序编码，降低上下编码混淆。
7. 发布风险文案：发布风险 warning 改为“非阻塞提醒”，说明资料缺口为可确认提醒，仅硬门禁阻塞发布。
8. 静态 404 噪音：补充 `favicon.svg` 并在 `index.html` 显式引用，减少浏览器默认 favicon 请求噪音。

### 9.3 目标效果

- 两条业务线完成后，PLM 侧状态、时间轴完成态、Dashboard 弹窗和项目中心详情保持一致。
- 钉钉完成回传不再只停留后端 warn，成功、失败、缺配置、缺 inbound 均有 outbound 记录可追踪。
- 用户可以在工作台明确区分“敲定投产工序”和“确认投产颜色”。
- 项目详情颜色、材质、负责人和工艺编码展示更接近业务语言，减少误判。
- 发布风险默认折叠，且文案区分非阻塞提醒和阻塞门禁。

### 9.4 测试结果

已执行并通过：

- `npm run test:run -- src/views/dashboard/__tests__/DashboardView.spec.ts src/views/project/__tests__/project-m4-panels.spec.ts src/views/project/__tests__/project-m5-release-gate-panel.spec.ts`
  - 3 个测试文件通过，41 个测试用例通过。
- `npm run type-check`
  - Vue / TypeScript 类型检查通过。
- `.codex_tmp\apache-maven-3.9.9\bin\mvn.cmd -Dtest=DingTalkProjectCompletionReturnServiceTest test`
  - 10 个后端测试用例通过。
- `node .codex_tmp\playwright-new-product-timeline-release-gate.cjs`
  - 通过；截图输出：`docs/文件沉淀/2026-08-11-PLM-new-product-timeline-release-gate-collapse.png`。
- `node .codex_tmp\playwright-dashboard-color-route-check.cjs`
  - 通过；报告输出：`.codex_tmp/dashboard-color-route-check-result.json`。
  - 检查项：Dashboard 投产颜色入口、released 旧详情链接、颜色 / 材质 / 负责人可读展示。

### 9.5 测试过程问题记录

- 首次运行 `.codex_tmp/playwright-dashboard-color-route-check.cjs` 时，mock 时间轴被设置为 `timelineCompleted=true`，导致 Dashboard 操作区不显示“确认投产颜色”按钮；该问题属于测试数据构造错误。已将 mock 调整为“当前投产决策节点”，重跑通过。
- 当前 Playwright 检查使用前端 dev server + API route mock 覆盖交互与展示；真实后端数据链路的完整推进仍建议在稳定测试数据窗口再跑一次全链路脚本。
