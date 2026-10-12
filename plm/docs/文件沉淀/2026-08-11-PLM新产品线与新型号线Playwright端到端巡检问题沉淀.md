# 2026-08-11 PLM 新产品线与新型号线 Playwright 端到端巡检问题沉淀

## 1. 背景

本次按用户指定，对截图中的两条测试数据做 Playwright 只读巡检，不修改业务代码，重点检查：

- 新产品线是否能从工作台 / 项目中心进入并查看关键模块。
- 新型号线是否能从工作台 / 项目中心进入并查看关键模块。
- 页面体验、历史已修问题的回归状态、模块数据是否同步。
- 巡检过程中发现的问题统一沉淀到文档，后续再按确认范围改代码。

执行前已阅读：

- `D:\work\资料\PLM\docs\文件沉淀\开发提示词.md`

## 2. 测试对象

| 业务线 | 项目 / Product ID | 产品编码 | 产品名称 | 类型 | 当前状态 |
| --- | ---: | --- | --- | --- | --- |
| 新产品线 | 19250 | PRD-HE-0005 | 超队5.0 | product_line | developing / 开发中 |
| 新型号线 | 19249 | PRD-ALTERN-0004 | Alterna幻甲 SM S281 | model_variant | developing / 开发中 |

登录账号：

- `engineer01 / plm123456`

环境：

- 前端：`http://127.0.0.1:5174`
- 后端：`http://127.0.0.1:8080`
- 测试方式：Playwright + 后端只读 API 交叉验证

## 3. 测试证据

Playwright 脚本：

- `.codex_tmp/playwright-two-lines-audit.cjs`
- `.codex_tmp/playwright-dashboard-two-lines-audit.cjs`
- `.codex_tmp/dashboard-recheck-two-lines.cjs`

结果文件：

- `.codex_tmp/two-lines-audit-result.json`
- `.codex_tmp/dashboard-two-lines-audit-result.json`

截图：

- `docs/文件沉淀/2026-08-11-PLM-two-lines-audit-product-line.png`
- `docs/文件沉淀/2026-08-11-PLM-two-lines-audit-model-variant.png`

说明：

- 第一轮 Dashboard 脚本只等待页面标题，未等待 `/api/v1/workbench/projects/in-progress` 返回，曾误判两条卡片未显示。
- 复核脚本等待工作台接口 200 后确认：工作台首页实际能显示 `19250`、`19249` 两张进行中项目卡片。
- 页面运行过程中有一条静态资源 404 控制台错误，但 `requestfailed` 为空，未阻塞业务页面加载，后续可单独定位 favicon / 静态资源路径。

## 4. 接口基线

### 4.1 工作台进行中项目

接口：

- `GET /api/v1/workbench/projects/in-progress?page=1&size=20`

复核结果：

- HTTP 200。
- 返回 20 条进行中项目。
- 返回内容包含 `productId=19250` 和 `productId=19249`，且位于列表前两位。
- 前端等待接口完成后，Dashboard 卡片均可显示。

工作台卡片文本摘要：

- `19250`：超队5.0，PRD-HE-0005，开发中，产品立项，完成度 5%。
- `19249`：Alterna幻甲 SM S281，PRD-ALTERN-0004，开发中，产品立项，完成度 6%。

### 4.2 新产品线 19250

只读接口摘要：

- `GET /projects/19250/summary`
  - 状态：`developing`
  - 当前节点：第 1 步，产品立项
  - 负责人：`null`
- `GET /projects/19250/timeline`
  - `started=true`
  - `timelineCompleted=false`
  - 当前节点：`PRODUCT_LINE_INIT_CREATE`
  - 当前节点未确认
- `GET /projects/19250/release-gate`
  - `passed=false`
  - `blocking=true`
  - `missingItems=7`
  - 包含当前时间轴未到最终节点、当前门禁节点未确认、BOM 未冻结、工艺路线未锁定、图纸缺失、SOP/SIP 缺失、测试资料缺失。
- `GET /projects/19250/boms`
  - 0 条。
- `GET /projects/19250/process-routes`
  - 0 条。
- `GET /products/19250/attachments`
  - 空数组。

### 4.3 新型号线 19249

只读接口摘要：

- `GET /projects/19249/summary`
  - 状态：`developing`
  - 当前节点：第 1 步，产品立项
  - 负责人：`null`
- `GET /projects/19249/timeline`
  - `started=false`
  - `timelineCompleted=false`
  - 阻塞原因：请先完成新型号项目信息完善表，确认后才能进入项目时间轴。
- `GET /projects/19249/requirement-form`
  - 状态：`draft`
  - 钉钉审批号：`202608110931000312050`
  - 型号：`SM S281`
  - 产品特定编码：`DN`
  - 手机型号编码：`1291`
  - 颜色：`31 Transparente` 已选。
- `GET /projects/19249/release-gate`
  - `passed=false`
  - `blocking=true`
  - `missingItems=7`
  - 后端已有发布门禁风险，但项目详情页未显示发布风险面板。
- `GET /projects/19249/boms`
  - 1 条候选 BOM。
  - 页面可见：`BOM-NDN4030000031-002 - ERP 历史 BOM NDN4030000031`，状态 draft，6 项物料。
- `GET /projects/19249/process-routes`
  - 1 条工艺路线。
  - 页面可见：`PRD-ALTERN-0004-0000 / Alterna幻甲 工艺路线 - SM S281`，状态 confirmed，4 个工序已落库。
- `GET /products/19249/attachments`
  - 空数组。

## 5. 新产品线巡检结果

### 5.1 已通过

- 项目中心可打开 `PRD-HE-0005 / 超队5.0` 详情。
- 基础信息、项目流程、BOM 管理、工序明细、资料区等页签可切换。
- 当前节点来自后端时间轴，显示为“产品立项 / 开发中 / 未确认”。
- 页面存在“确认当前节点”按钮和“退回”按钮；未直接出现推进按钮，符合当前节点未确认状态。
- 发布风险折叠已生效：
  - 初始不渲染风险明细。
  - 点击展开后显示 7 条风险和统计。
- BOM、工艺路线、资料区均与后端一致为空。
- 未出现 axios 明显错误文案，页面未白屏。

### 5.2 问题

| 等级 | 问题 | 影响 | 建议 |
| --- | --- | --- | --- |
| P1 | 基础信息颜色、材质以 JSON 字符串展示，如 `["02 Negro","03 Humo","04 Blanco"]`、`["TPU","PC"]` | 业务用户难以阅读，且与标签式展示预期不一致 | 前端统一对数组字符串做解析，展示为标签或逗号分隔文本；后端可补充结构化 VO 字段 |
| P2 | 负责人显示 `--`，后端 `ownerUserName=null` | 工作台、详情、任务归属缺少责任人，后续推进责任不清 | 从钉钉创建入口或项目创建入口同步负责人；无负责人时给出待分配提示 |
| P3 | 页面有静态资源 404 控制台错误 | 当前不阻塞业务，但会干扰巡检和错误监控 | 定位 404 URL，修正静态资源或 favicon 配置 |

## 6. 新型号线巡检结果

### 6.1 已通过

- 项目中心可打开 `PRD-ALTERN-0004 / Alterna幻甲 SM S281` 详情。
- 基础信息能显示型号、产品特定编码、手机型号编码、颜色编码、模具编码等关键字段。
- BOM 已同步到项目：
  - 页面显示 1 条候选 BOM。
  - 6 项物料可见。
  - 提示供应商缺失、成本缺失，和 draft 候选状态一致。
- 工艺路线已同步到项目：
  - 页面显示 1 条 confirmed 路线。
  - 4 个工序关系已落库。
- 资料区为空，与后端附件接口一致。
- Dashboard 复核通过：工作台能显示该项目卡片。

### 6.2 问题

| 等级 | 问题 | 影响 | 建议 |
| --- | --- | --- | --- |
| P0 | 新型号线时间轴被完善表阻塞，但项目详情页没有直接显示完善表入口 / 确认入口 | 用户进入详情后知道“要完善表”，但不知道在哪里完成，流程无法自助推进 | 在新型号详情“项目流程”阻塞态下嵌入 `ModelVariantRequirementForm` 或给出明确跳转入口 |
| P1 | 新型号线后端有发布门禁风险，但项目详情页未显示发布风险面板 | 新产品线与新型号线发布前风险口径不同步，用户无法在详情页预检发布风险 | 新型号详情同步接入 `ProjectReleaseGatePanel`，并保持与新产品线一致的折叠体验 |
| P1 | 初始详情可看到一套“待开始”的流程列表，切到项目流程后又显示“完善表未完成，不能进入时间轴” | 同一项目在不同位置给出不同流程状态，用户会误以为时间轴已生成 | 未启动时统一展示阻塞态，不渲染完整流程列表；或将列表置灰并标明来源 |
| P2 | 基础信息颜色显示为 `--`，但完善表里已有 `31 Transparente` 已选 | 新型号颜色在完善表、基础信息、BOM 颜色之间未完全贯通，容易误判颜色未同步 | 基础信息优先展示颜色编码 + 颜色名称，来源可为 requirement form / Product 字段 / BOM 色组 |
| P2 | 负责人显示 `--`，后端 `ownerUserName=null` | 项目责任归属不清 | 同新产品线，创建 / 集成入口补齐负责人映射 |

## 7. 历史问题回归情况

| 历史问题 | 本次覆盖情况 | 结论 |
| --- | --- | --- |
| 完成后直接发布，不经过评审状态 | 两条测试数据均在开发中第 1 步，未跑到完成 / 发布动作 | 本次数据无法验证最终状态流转；页面未出现 reviewing 状态 |
| 投产颜色显示异常 | 两条测试数据均未到投产节点 | 未覆盖投产节点；但发现基础信息颜色仍有 JSON / 空值展示问题 |
| 运模快递单号仅保存单号和时间，取消物流轨迹 | 两条测试数据均未到运模节点 | 本次未覆盖运模节点 |
| 时间轴最后一步完成后自动变为完成状态 | 两条测试数据均未到最后一步 | 本次未覆盖最终完成态 |
| 新型号线完成后钉钉代同意 | 两条测试数据均未到最后运模完成节点；补查代码发现链路存在但依赖条件较多 | 当前不能认为已验证通过，需单独作为完成态联动问题跟进 |
| 新产品项目发布风险折叠 | 覆盖 `19250` 新产品线 | 已生效 |
| 新产品时间轴完成态收口与项目发布风险折叠 | 当前未到完成态；发布风险折叠覆盖 | 折叠已验证，完成态未覆盖 |

## 8. 模块同步情况

| 模块 | 新产品线 19250 | 新型号线 19249 | 结论 |
| --- | --- | --- | --- |
| 工作台首页 | 卡片可显示 | 卡片可显示 | 已同步；第一次空卡片为测试脚本等待误判 |
| 项目中心列表 | 可显示并打开 | 可显示并打开 | 已同步 |
| 基础信息 | 可显示，但颜色 / 材质体验差，负责人为空 | 可显示，但颜色名称未贯通，负责人为空 | 部分同步，展示需优化 |
| 项目流程 | 已启动，停留产品立项未确认 | 未启动，被完善表 draft 阻塞 | 状态同步正确，但新型号缺少详情内处理入口 |
| 发布门禁 | 后端有 7 条风险，前端折叠显示 | 后端有 7 条风险，详情页未显示 | 新型号前端模块未同步 |
| BOM | 0 条，页面为空 | 1 条 draft BOM，页面可见 | 与后端一致 |
| 工艺路线 | 0 条，页面为空 | 1 条 confirmed 路线，页面可见 | 与后端一致 |
| 附件 / 资料区 | 空 | 空 | 与后端一致 |

## 9. 建议后续修复清单

### P0 必修

1. 新型号线详情页补齐“完善表确认入口”。
   - 目标效果：用户看到阻塞原因后，可直接在详情页完成或跳转完成新型号项目信息完善表。
   - 逻辑要求：完善表 `status=draft` 时禁止进入真实时间轴，但提供可操作入口；确认后刷新时间轴和当前节点。

2. 新型号线完成后钉钉代同意需要单独联调验证并收口。
   - 当前代码触发点：确认最后节点后，`TimelineActionServiceImpl` 调用 `DingTalkProjectCompletionReturnService.handleProjectCompleted()`。
   - 当前触发条件：产品类型必须是 `model_variant`，当前节点必须是 `MODEL_VARIANT_MOLD_TRANSFER`，且存在 `integration_type=model_variant` 的钉钉 inbound 记录。
   - 当前代同意条件：inbound 原始 payload 里能取到 `taskId/approvalTaskId/task_id`，或通过钉钉流程实例查询能查到运行中 taskId；同时必须配置 `DINGTALK_AUTO_APPROVER_USER_ID` 和有效 `DINGTALK_OUTBOUND_ENDPOINT`。
   - 风险：如果 `DINGTALK_OUTBOUND_ENDPOINT` 为空，当前客户端会返回 `dry_run`，不会真实调用钉钉官方代同意；如果 inbound 只保存 `sourcePayloadJson` 且其中没有 taskId，后续查询失败时会保存失败出站记录，不会代同意。
   - 建议：完成态联调时增加出站记录检查和错误提示，把 dry_run、taskId 缺失、自动审批人未配置、钉钉接口失败明确展示到项目详情或操作日志中；必要时在 inboundRecord 中兜底保存 DTO 的 `taskId/approvalTaskId` 到 sourcePayloadJson。

### P1 高优先级

1. 新型号线详情页同步发布风险面板。
   - 目标效果：与新产品线一致，初始折叠，展开后显示 `/projects/{projectId}/release-gate` 的 `missingItems`。
   - 逻辑要求：同一发布门禁 API 在 product_line / model_variant 均可视。

2. 统一未启动时间轴展示。
   - 目标效果：详情初始态和“项目流程”页签状态一致，避免先看到待开始流程列表、后看到阻塞提示。
   - 逻辑要求：`timeline.started=false` 时统一走阻塞态组件；需要展示流程定义时必须置灰并明确“尚未启动”。

3. 修复颜色 / 材质展示。
   - 目标效果：JSON 数组字符串展示为标签；新型号基础信息展示 `31 Transparente`，不再是 `--`。
   - 逻辑要求：前端对数组字符串兼容解析；后端后续可补充结构化字段，避免 UI 解析业务 JSON。

### P2 中优先级

1. 项目负责人同步。
   - 目标效果：工作台卡片、项目详情、时间轴动作区显示明确负责人或待分配状态。
   - 逻辑要求：钉钉入口、项目创建入口、后端 VO 的 `ownerUserName` 口径一致。

2. 静态资源 404 清理。
   - 目标效果：Playwright 控制台无无关 404 噪音。
   - 逻辑要求：定位缺失资源路径并补齐或移除引用。

## 10. 本次未修改业务代码

本次只新增 / 使用巡检证据：

- 新增临时复核脚本：`.codex_tmp/dashboard-recheck-two-lines.cjs`
- 新增沉淀文档：`docs/文件沉淀/2026-08-11-PLM新产品线与新型号线Playwright端到端巡检问题沉淀.md`

未修改前端业务代码、后端业务代码、数据库迁移和配置。

## 11. 2026-08-11 工作台时间轴推动实测

用户要求从工作台时间轴开始推动项目后，使用 Playwright 从 Dashboard “进行中的产品”卡片进入项目进度弹窗，对两条测试数据做了实际 UI 推动。

测试脚本：

- `.codex_tmp/playwright-push-dashboard-timeline.cjs`

测试结果文件：

- `.codex_tmp/push-dashboard-timeline-result.json`

### 11.1 新产品线 PRD-HE-0005

操作路径：

1. 打开 Dashboard。
2. 点击工作台卡片 `PRD-HE-0005 / 超队5.0`。
3. 在“项目进度”弹窗点击“确认当前节点”。
4. 在确认弹窗备注中填写：`Playwright 从工作台开始推动 PRD-HE-0005`。

接口结果：

- `POST /api/v1/projects/19250/timeline/PRODUCT_LINE_INIT_CREATE/confirm`
- HTTP 200。
- 返回 `code=0`。
- `beforeStepNo=1`
- `currentStepNo=2`
- `currentNodeKey=PRODUCT_LINE_INIT_APPROVE`
- `currentNodeName=确认立项`
- `currentConfirmed=false`
- `productStatus=developing`
- `logId=1089`
- `warnings=[]`

复核结果：

- 后端时间轴 `currentStepNo=2`。
- 当前阶段为“立项确认”。
- 当前小节点为“确认立项”。
- 第 1 步“产品立项”显示为 completed。
- 第 2 步“确认立项”显示为 current。

结论：

- 新产品线从工作台时间轴推动第 1 步成功。
- 工作台弹窗动作、后端时间轴、操作日志能联动。

发现的问题：

| 等级 | 问题 | 影响 | 建议 |
| --- | --- | --- | --- |
| P2 | 工作台时间轴弹窗里“强制推进”按钮始终可见，但点击后只是提示后续接入 | 用户会以为可以绕过当前节点或门禁，实际不可用 | 未接入前隐藏或禁用，并加 tooltip 说明 |
| P2 | 第 1 步确认后，当前仍在同一大阶段“立项确认”，但页面主卡片仍显示“立项确认 / 进行中”，变化主要体现在“小节点第 2 步” | 对用户来说推进反馈不够强，容易误以为没有推进 | 成功后突出展示“已推进到第 2 步：确认立项” |

### 11.2 新型号线 PRD-ALTERN-0004

操作路径：

1. 打开 Dashboard。
2. 点击工作台卡片 `PRD-ALTERN-0004 / Alterna幻甲 SM S281`。
3. 项目进度弹窗先显示“新型号项目信息完善表”，因为时间轴未启动。
4. 在完善表中选择订单类型“市场需求”。
5. 点击“确认并进入下一步”。
6. 完善表确认成功后，工作台弹窗切换为时间轴。
7. 点击“确认当前节点”。
8. 在确认弹窗备注中填写：`Playwright 从工作台开始推动 PRD-ALTERN-0004`。

接口结果：

- `POST /api/v1/projects/19249/requirement-form/confirm`
  - HTTP 200。
  - 完善表从 `draft` 变为 `confirmed`。
  - `requirementType=market_requirement`。
- `POST /api/v1/projects/19249/timeline/MODEL_VARIANT_INIT_CREATE/confirm`
  - HTTP 200。
  - 返回 `code=0`。
  - `beforeStepNo=1`
  - `currentStepNo=2`
  - `currentNodeKey=MODEL_VARIANT_INIT_APPROVE`
  - `currentNodeName=确认立项`
  - `currentConfirmed=false`
  - `productStatus=developing`
  - `logId=1093`
  - `warnings=[]`

复核结果：

- 后端时间轴 `started=true`。
- 后端时间轴 `currentStepNo=2`。
- 当前阶段为“立项确认”。
- 当前小节点为“确认立项”。
- 第 1 步“产品立项”显示为 completed。
- 第 2 步“确认立项”显示为 current。
- 完善表状态已为 `confirmed`。

结论：

- 新型号线可以从工作台入口完成“完善表确认 -> 时间轴启动 -> 确认第 1 步 -> 推进到第 2 步”的闭环。
- 之前记录的“项目详情页缺少完善表入口”仍然成立，但 Dashboard 工作台弹窗已经具备完善表入口。

发现的问题：

| 等级 | 问题 | 影响 | 建议 |
| --- | --- | --- | --- |
| P1 | 新型号线项目详情页仍未同步 Dashboard 的完善表处理入口 | 用户从工作台可处理，从项目中心详情不可处理，入口不一致 | 项目详情页未启动时间轴时复用 `ModelVariantRequirementForm` |
| P2 | 完善表“订单类型”为空时页面只有 Select，占位和错误提示不够业务化 | 用户不知道必须先选订单类型才能启动时间轴 | 占位改为“请选择订单类型”，确认失败时在字段附近提示 |
| P2 | 工作台弹窗确认完善表后直接切到时间轴，但没有醒目说明“完善表已确认，时间轴已启动” | 成功反馈主要依赖 toast，回看页面不够直观 | 在弹窗顶部短暂展示成功提示或在时间轴摘要中显示启动来源 |
| P2 | “保存草稿 / 确认并进入下一步”等按钮在编码异常环境下显示为乱码 | 当前测试终端和部分文本输出可见乱码，影响核对 | 统一确认前端源文件和终端读取编码为 UTF-8 |

### 11.3 控制台和网络

- Playwright 捕获到 1 条控制台错误：`Failed to load resource: the server responded with a status of 404 (Not Found)`。
- `requestfailed` 为空。
- 本次推动核心接口均返回 HTTP 200。

### 11.4 与“新型号完成后代同意”的关系

本次只从第 1 步推动到第 2 步，未到新型号最后节点 `MODEL_VARIANT_MOLD_TRANSFER`，因此仍未触发“完成后钉钉代同意”链路。

后续如果要验证代同意，需要继续把新型号线推进到最后“运模”节点，并确认：

- 运模节点完成时 Product 状态是否进入 `released`。
- 是否生成 `integration_type=model_variant_mold_transfer_completed` 的出站记录。
- 出站记录 `processing_status` 是 `success` 还是 `failed`。
- `source_payload_json` 是否含 `taskId`、`actionerUserId`、`approvalInstanceId`。
- 当前环境是否配置真实 `DINGTALK_OUTBOUND_ENDPOINT`，避免只出现 `dry_run`。

## 12. 2026-08-11 继续推动到完成态后的终态巡检

用户确认如果需要加工艺或添加 BOM，可以直接加测试数据。本轮未修改前后端业务代码，只补齐两条测试项目完成时间轴所需的测试 BOM、测试工艺路线和投产确认数据，并使用 Playwright 从工作台时间轴继续推动到最后节点。

本轮新增 / 使用的验证脚本：

- `.codex_tmp/seed-timeline-test-data.cjs`
- `.codex_tmp/playwright-complete-dashboard-timeline.cjs`
- `.codex_tmp/playwright-dashboard-two-lines-audit.cjs`
- `.codex_tmp/playwright-two-lines-audit.cjs`
- `.codex_tmp/playwright-final-two-lines-audit.cjs`

本轮结果文件：

- `.codex_tmp/seed-timeline-test-data-result.json`
- `.codex_tmp/complete-dashboard-timeline-result.json`
- `.codex_tmp/dashboard-two-lines-audit-result.json`
- `.codex_tmp/two-lines-audit-result.json`
- `.codex_tmp/final-two-lines-audit-result.json`

### 12.1 测试数据补齐情况

| 项目 | 补齐内容 | 结果 |
| --- | --- | --- |
| 新产品线 `19250 / PRD-HE-0005 / 超队5.0` | 新增测试工艺路线 `processId=450`，新增测试 BOM `productBomId=65`，使用颜色字典 `02 Negro`，确认当前 BOM 版本 | BOM 状态为 `released`，工艺路线状态为 `confirmed`，投产确认可读取 1 条工序和 1 个颜色 |
| 新型号线 `19249 / PRD-ALTERN-0004 / Alterna幻甲 SM S281` | 新增测试工艺路线 `processId=452`，新增测试 BOM `productBomId=66`，使用颜色字典 `02 Negro`，确认当前 BOM 版本 | BOM 状态为 `released`，工艺路线状态为 `confirmed`，投产确认可读取 1 条工序和 1 个颜色 |

说明：

- 本轮没有使用 `/boms/{bomId}/publish`，因为发布动作会被“当前工作台时间轴节点不允许冻结或发布 BOM”门禁阻断。
- 实际使用 `/boms/{bomId}/confirm-current-version` 将测试 BOM 作为当前确认版本，满足时间轴继续推动所需的 BOM 门禁。
- Dashboard 目前只提供“敲定投产工序”入口，没有单独暴露“确认投产颜色”入口；本轮能够继续完成，是因为 `POST /api/v1/projects/{projectId}/production-routes/confirm` 的返回和落库同时写入了 `selectedOperationCount=1`、`selectedColorCount=1`、`colors=["Negro"]`。

### 12.2 时间轴推动路径和最终状态

| 项目 | 起点 | 关键门禁 | 终点 | 终态 |
| --- | --- | --- | --- | --- |
| 新产品线 `19250` | 工作台弹窗中从样品/工艺阶段继续确认 | 第 10 步“敲定工序”时打开投产确认弹窗并确认测试工序；最后节点依赖颜色已确认 | 第 22 步 `PRODUCT_LINE_PRODUCTION_DECISION_STEP / 投产决策` | `status=released`，`timelineCompleted=true`，`currentConfirmed=true`，末节点显示 completed |
| 新型号线 `19249` | 工作台弹窗中从样品/工艺阶段继续确认 | 第 10 步“敲定工序”时打开投产确认弹窗并确认测试工序；最后节点依赖颜色已确认 | 第 18 步 `MODEL_VARIANT_MOLD_TRANSFER / 运模` | `status=released`，`timelineCompleted=true`，`currentConfirmed=true`，`moldTransferAt=2026-08-11T02:58:53.242306`，末节点显示 completed |

后端终态接口复核：

- `GET /api/v1/projects/19250`：`status=released`，`currentStepNo=22`，`currentNodeName=投产决策`，`totalCost=2.88`。
- `GET /api/v1/projects/19250/timeline`：`timelineCompleted=true`，第 22 步 `PRODUCT_LINE_PRODUCTION_DECISION_STEP` 为 `completed`，`currentConfirmed=true`。
- `GET /api/v1/projects/19249`：`status=released`，`currentStepNo=18`，`currentNodeName=运模`，`colorCode=02`，`color=Negro`，`finishedProductCode=NDN4030129131`，`totalCost=3.21`。
- `GET /api/v1/projects/19249/timeline`：`timelineCompleted=true`，第 18 步 `MODEL_VARIANT_MOLD_TRANSFER` 为 `completed`，`currentConfirmed=true`。

结论：

- “时间轴最后一步完成后自动变为完成状态”的修复在两条线均验证通过。
- “完成之后直接到发布状态，不经过评审状态”的主状态流转在两条线均验证通过；接口和项目列表均显示 `released`，未出现 `reviewing`。
- 工作台“进行中的产品”不再显示 `19250` 和 `19249`，符合 released 后退出进行中工作台的预期。

### 12.3 模块同步情况

| 模块 | 新产品线 `19250` | 新型号线 `19249` | 结论 |
| --- | --- | --- | --- |
| 工作台 | 完成后工作台卡片消失 | 完成后工作台卡片消失 | 符合“只保留当前推进中对象”的设计 |
| 项目列表 | `status=released`，`currentStepNo=22` | `status=released`，`currentStepNo=18` | 与后端详情一致 |
| 项目详情 | 状态显示“已发布”，当前节点为“投产决策” | 接口显示“已发布 / 运模”，但旧 `tab=in_progress` 路由无法稳定打开新型号详情 | 新型号 released 后详情入口/路由需要复核，不应依赖进行中 tab |
| 时间轴 | 末节点 completed，确认按钮消失 | 末节点 completed，确认按钮消失 | 完成态收口通过 |
| BOM | 测试 BOM `released`，可被发布门禁统计为 `frozenBomCount=1` | 测试 BOM `released`，同时仍存在历史 draft BOM | 当前版本 BOM 可用；历史 draft BOM 需要页面上避免误导 |
| 工艺路线 | 测试路线 `confirmed`，投产确认可读取 | 测试路线 `confirmed`，同时仍存在历史 confirmed 路线 | 投产确认同步通过；发布风险仍提示缺少 locked/frozen 路线 |
| 投产确认 | `selectedOperationCount=1`，`selectedColorCount=1`，`colors=["Negro"]` | `selectedOperationCount=1`，`selectedColorCount=1`，`colors=["Negro"]` | 工序和颜色已同步 |
| 发布门禁 | `passed=true`，`blocking=false`，但保留 4 条 warning | `passed=true`，`blocking=false`，但保留 4 条 warning | 符合“资料缺口提示确认，不再作为发布硬门禁”的改造目标 |
| 资料区 | `documentCount=0`，页面为空 | `documentCount=0`，页面为空 | 与发布门禁 warning 一致 |

发布门禁 warning 明细两条线一致：

- `PROCESS_ROUTE_NOT_LOCKED`：缺少已锁定或已冻结工艺路线。
- `DRAWING_FILE_MISSING`：缺少图纸文件。
- `SOP_OR_SIP_FILE_MISSING`：缺少 SOP 或 SIP 文件。
- `TESTING_FILE_MISSING`：缺少测试资料。

### 12.4 钉钉代同意 / 外部回传检查

数据库 `plm_integration_record` 复核结果：

- `19249` 存在 `integration_type=model_variant`、`direction=inbound`、`processing_status=success` 的入站记录，`external_instance_id=GNZBx13QSeiMhmx3ciNWvQ04891786411891`。
- `19250` 存在 `integration_type=product_line`、`direction=inbound`、`processing_status=success` 的入站记录，`external_instance_id=8xghx1nNQQSRqAJcSagt4g04891786413090`。
- 本轮完成 `19249` 运模后，未查到 `project_id=19249`、`integration_type=model_variant_mold_transfer_completed`、`direction=outbound` 的出站记录。
- 本轮完成 `19250` 投产决策后，未查到 `project_id=19250`、`integration_type=product_line_completed_cc`、`direction=outbound` 的出站记录。

结论：

- PLM 内部时间轴和 Product 状态已经完成并发布。
- 钉钉“完成后代同意 / 完成通知”没有在本轮测试数据上产生出站记录，不能认为外部回传链路已跑通。
- 从代码链路看，最后节点确认后应通过 `TimelineActionServiceImpl.triggerDingTalkCompletionReturn()` 在事务提交后调用 `DingTalkProjectCompletionReturnService.handleProjectCompleted()`；但数据库没有对应 outbound，建议后续单独排查 afterCommit 是否执行、`dingTalkProjectCompletionReturnService` 是否注入、`handleProjectCompleted` 是否因异常被 warn 吞掉、以及日志中是否有 `DingTalk project completion return failed after PLM timeline completion`。

### 12.5 仍存在的问题和优化项

| 等级 | 问题 | 影响 | 建议 |
| --- | --- | --- | --- |
| P0 | 新型号线 `19249` 完成运模后未产生 `model_variant_mold_transfer_completed` outbound 记录 | 用户期望的“PLM 完成后钉钉代同意”没有形成可追踪结果，外部审批可能不会自动同意 | 增加完成后回传结果可观测性；afterCommit 执行失败不能只写后端 warn，需落 integration 失败记录或操作日志 |
| P1 | 新型号 released 后旧的 `tab=in_progress&productId=19249` 详情路由打不开 / 不稳定 | 用户从历史链接或完成前页面刷新进入时可能找不到已发布新型号详情 | 项目详情按 `productId` 直查时不要强依赖当前 tab；released 项目自动切换到全部或归档视图 |
| P1 | 新型号完成后工作台弹窗曾短暂显示顶部“开发中”，且阶段标题出现“选择订单类型” | 后端已 released，但弹窗头部状态和阶段标题没有及时刷新，用户会误判未完成 | 最后节点确认成功后刷新 `activeProgressProject` 和时间轴定义摘要；标题应取当前末节点“运模” |
| P1 | Dashboard 只有“敲定投产工序”入口，没有单独的颜色确认入口 | 颜色门禁依赖工序确认的副作用通过，用户不清楚颜色是否已确认 | 在投产颜色节点显示明确入口，或在工序确认成功后展示“已同步确认颜色：02 Negro” |
| P1 | 新产品线基础信息颜色仍显示 JSON 字符串 `["02 Negro","03 Humo","04 Blanco"]` | 业务信息可读性差，也影响投产颜色问题回归观感 | 前端兼容 JSON 数组字符串并渲染为标签；后端后续补结构化颜色字段 |
| P1 | 新型号 `colorCode=02 / color=Negro`，但 `finishedProductCode=NDN4030129131` 仍带原始 `31` 尾码 | 颜色字段与成品编码可能不一致，影响编码继承和后续 ERP/BOM 对齐 | 补充新型号颜色变更后的成品编码重算规则或明确不重算的业务边界 |
| P2 | 项目负责人 `ownerUserName=null` | 工作台、详情、时间轴责任人信息不完整 | 钉钉入站、项目创建、VO 映射统一补齐负责人 |
| P2 | 控制台仍有静态资源 404 | Playwright 日志有噪音，真实错误不易分辨 | 定位缺失资源路径，补齐或移除引用 |
| P2 | 发布门禁已 `passed=true` 但仍显示缺资料 warning | 逻辑正确，但用户可能误解为发布失败 | 文案强调“可发布，但建议补齐资料”，并区分阻塞项和提醒项 |

### 12.6 历史问题回归结论更新

| 历史问题 | 本轮结论 |
| --- | --- |
| 完成后直接发布，不经过评审 | 通过。两条线最终均为 `released`，未进入 `reviewing`。 |
| 时间轴最后一步完成后自动变为完成 | 通过。新产品第 22 步、新型号第 18 步均为 `completed` 且 `currentConfirmed=true`。 |
| 新产品项目发布风险折叠 | 通过。风险内容默认未渲染，展开后显示 warning 明细。 |
| 投产颜色显示异常 | 部分通过。投产确认接口颜色为 `Negro`，但新产品基础信息仍显示 JSON 字符串。 |
| 运模快递单号仅保存单号和时间 | 本轮未覆盖快递单号录入；只覆盖了运模节点完成和 `moldTransferAt` 自动写入。 |
| 新型号完成后钉钉代同意 | 未通过 / 未跑通。`19249` 完成后没有产生 outbound 出站记录。 |

### 12.7 本轮未修改业务代码

本轮只新增 / 修改巡检脚本和沉淀文档，未修改：

- `plm-web/src/**`
- `plm-server/src/**`
- 数据库迁移脚本
- 业务配置文件

本轮实际改动范围：

- 新增 `.codex_tmp/playwright-final-two-lines-audit.cjs`。
- 更新 `docs/文件沉淀/2026-08-11-PLM新产品线与新型号线Playwright端到端巡检问题沉淀.md`。

本轮测试会对测试项目数据产生推进结果：

- `19250 / PRD-HE-0005` 已被推进到 `released`。
- `19249 / PRD-ALTERN-0004` 已被推进到 `released`。
