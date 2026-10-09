# 金蝶式采购流程 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox syntax. One implementation writer, one QA database owner, and one production release owner at a time; independent read-only reviews may run separately.

**Goal:** 复用原生采购链与钉钉来源，提供整单/合并入库、应付和付款，并确保新库存取消在重算及账务核对后才显示冲销完成。

**Architecture:** Integration Request 是唯一持久操作与进度记录；原生控制器负责业务单据、库存和账务。普通操作继续同事务，新库存取消采用已确认的受理/原生重算/最终核对三个阶段。共用范围服务和锁协议保护标准入口、批量入口和原生后台任务，不复制库存执行器。

**Tech Stack:** Frappe/ERPNext 16、MariaDB、China Finance、现有 Branding JavaScript、pytest/unittest、Node test runner、隔离 Docker Compose。

---

批准范围：钉钉可靠来源生成原生订单草稿、人工审核、逐单/合并入库、单独确认应付与部分/合并付款。采购主表仅真实订单，缺项来源在同页待完善标签。内部 WMS 复用原生库存。生产测试不提交业务单据。

### 2026-10-09 执行收口（用户最新要求）

用户要求底层边界不拆过细、减少重复验证、实现干净直接。保留已经完成的必要权限、事务、幂等及一致性约束，停止新增 C2A3/C2A4 一类底层切片；以下按完整业务任务交付，不再逐小函数增加独立执行/审查轮次。

1. 采购整单物料表与待完善标签：候选 `daca632012d9434f86c20a052e8eb694ad0b6828` 加定向修复 `ee3b07dbba89996cf65607cf5d8d65e2f2e97e59` 已通过独立规格/质量审查。原生事件顺序发现的全选与首次路由两处问题已修复，只补对应测试。真实浏览器与批量动作接好后统一验收。
2. 逐单/合并入库、同公司/供应商/币种付款：直接扩展既有转换和付款服务、同一抽屉与集中操作栏；保留真实来源行和整批回滚，不新增平行业务服务。
3. 钉钉自动草稿：复用来源规范化、审批/版本/人工值保护和订单创建；完整可靠来源建草稿，缺项留待完善，外部读取失败整批回滚。
4. 异步冲销：按已批准设计一次接通原子受理、原生重算入口、只读最终校验和页面阶段。覆盖实际可发生的失败点；不重跑已验收底层 callback/closure 的全部变体。
5. 集成完成后集中执行一次完整候选回归、实际控制器测试、浏览器验收和联合发布。每个业务改动只运行受影响测试及必要故障用例；不把重复全套运行次数当完成证据。

本轮仍由一个 source/index 写入者、一个本地 QA 所有者执行；独立审查只读。生产写入继续由既定唯一发布负责人串行执行，不因本地开发开启第二条部署。

备份清理已有用户明确授权并交给该发布对话：先生成并验证当前完整恢复备份，精确列出旧 `material-ai-release-*` 归档，保留最新三份及当前版本必要回滚材料，删除其余已核实目标。GitHub 回退只覆盖代码，不代替数据库/附件恢复。生产执行结果须单独回读，不将授权当成已删除或已释放空间。

当前网格专项证据：实现者完整 Node 一次通过；统一采购纯 Python 136 passed/1 skipped；原生进度 site-free 单元 53 passed/37 subtests；资源测试 13 通过。主任务独立重跑两份受影响 Node 文件（80 项）及 diff-check 通过。该阶段没有本地业务数据库写入，也没有部署或线上验收。

唯一生产负责人 10:15 上海报告旧归档清理完成：固定清单 228 份、67,705,212,996 字节；保留最新三份、当前回滚材料与新完整备份。隔离恢复验证了 853 张数据库表和 594 个附件，不代表整套应用启动恢复验收。旧归档恢复点不可找回；生产仍原版本、采购发布 HOLD。外部扩盘/重启不计入本轮清理成果。

初始基线：`336c7054fbf7f4bfdfe459020ea5e677d556db60`；分支 `codex/kingdee-purchase-flow`。复用本对话已有工作树，不复制旧采购实现。

2026-10-09 发布版本再次校准：`cadd99c` 是 Docker image ID，不是 Git commit。六个生产容器的 Branding 标签为 `00fee003b9cdbe8b43ee314406afa62487fc3b59`；它在 GitHub 当前 `336c7054` 后另含 `ef9c1b8` 和 `00fee003`，不能用旧远端分支覆盖。主任务从发布负责人现有本地对象库精确取 `00fee003`，串行合入采购候选；保留其运营待办、导航、付款抽屉和来源长文本修复。冲突仅为资源版本与对应测试，合并后的共享 JS/CSS采用新缓存标记；受影响六份 Node（310 项）和资源测试（20 项）通过，没有业务数据库写入。最终整候选验收仍未完成、采购发布 HOLD。

OA app 当前内容基线 `c5dd3b939b93f22b0d4ec988acc000dcede1a923`：负责人逐一核对 25 个 tracked 文件与生产运行文件，缺失/多余/差异均为 0；运行目录没有 Git/版本标签，不能把内容哈希核对冒充运行 Git HEAD。其旧 PO on_submit 会无条件生成独立 PR 草稿；为实现未来新订单明确逐单/合并入库，下一任务前向替代这个重复 hook，不删除历史草稿、不改 Company 自动应付配置、不做运行时猴补。

批量功能冻结 `70dda576cb39bdc23dd81957c76c1531b8955f58`：复用 actions/payment/同抽屉，12 文件 +712/-71，其中业务 +433/-67，测试 +279/-4；7 个真实原生事务测试、86 单测/72 子场景、228 Node、13资源测试通过，最后两个受影响增强场景通过。现有自动 PR 草稿可明确继续编辑并整批审核；正常新订单合并仍依赖上述旧 hook 替代。浏览器、整候选回归和部署未完成，不记为整个采购流程交付。

## 实施顺序

- [x] 核对 Branding 远端与 Vultr 当前 image，协调唯一发布负责人。
- [x] 采购 JS 基线：128 个测试通过；不将旧 QA 报告算作当前验证。
- [x] 替换 Redis 唯一结果缓存为共用、持久化 Integration Request 严格基础边界；原生入口/可同步冲销/日志和提交前校验，未支持关联保持明确拒绝。Task 1A 已独立验收；新库存取消的分阶段例外仍在后续任务实现。
- [ ] 按已确认的狭义异步例外扩展库存取消：持久阶段、实际 RIV 及传播范围、前后端拦截、最终核对与恢复；其余业务继续同事务。
- [ ] 扩展既有原生转换和付款服务支持同主体合并；整批事务/来源行/当前余量与权限。
- [ ] 可靠钉钉来源自动草稿；不足字段保持待完善，人工值与历史付款保护不变。
- [ ] 复用紧凑列表与付款抽屉：真实 rowspan 明细、整单选择、订单/待完善标签、统一偏好迁移、集中动作。
- [ ] 分别进行规格审查、质量审查，修复后复审。
- [ ] 新的独立本地 Compose 数据库运行真实控制器故障注入、回滚/幂等及浏览器流程；不改变其他 QA 环境。
- [ ] 专项、全量、语法、资源/CI 检查；独立交付联动清单、校验点、测试结果与代码统计。
- [ ] 交给已协调的唯一发布负责人串行 Vultr 发布；核验 SHA、缓存、健康及线上只读操作。

## 复用与兼容

复用 purchase_document_actions、purchase_payment_service、purchase_source_service、compact_list、purchase_payments 与 ERPNext/中国财务原生服务。移除被替换的采购 Redis-only 事务实现和旧采购组合单元格默认值，不保留第二条采购联动逻辑。其他模块仍调用共用表格/抽屉，配置隔离保留其真实功能；保留标准表单及已保存草稿办理入口。所有动态钩子和外部调用须重新核对后才可删除。运营对话的共享文件改动按实际候选 SHA 串行合并，不覆盖。

严格边界：无关联模块记录不适用；不生成虚构销售/运营分摊，不新增库存流水，不修改盘点快照/公司自动应付配置，不写钉钉/WMS/银行外部系统。成功日志随事务，失败结构化运行日志独立留存。所有正式金额/数量使用原生精度。

## 已执行基线（不是最终验收）

- `node --test tests/*.test.js`：475 通过，零失败/跳过。采购专项子集 128 通过。
- 初始化 Frappe 后，actions/payment links/source service 的原有单元测试：126 通过。
- `python3 -m unittest -q tests.test_purchase_source_contract tests.test_unified_purchase_release tests.test_purchase_order_assets`：69 通过。
- `test_procurement_integration_qa.execute()`：7 个原生场景通过；最终 PO139、PR114、PI5、PE6、GL16、Payment Ledger8、User6、User Permission3 未变化。对齐当前财务服务后再次通过。
- 测试库只从本地合成库复制，不复制线上业务数据。独立 Compose 项目 `dlp-kingdee-purchase-qa`，`127.0.0.1:64248`，站点 `po-grid-qa.localhost`，数据库 `qa_procurement_5`，独立持久卷。
- 初始本地中国财务 voucher.py 与线上版本不一致，已只读复制线上 `4f019f91f36aa549df1854d2df0b60e20c01751c` 包到独立 QA。voucher.py SHA256 `bf91a573a920cabb810161cd893d78fdc4044d760611b6fc43522986ef43038e`，auto_invoice.py SHA256 `14fb90b7a55ed385bd4147e3879b0ce0e540d71e682091206fca12fcc0db5a6d`。生产未改动。
- 全应用 migrate 在原有 Overseas workspace 的 `Overseas Cost ERP Settings` 链接处失败；未修改该无关模块。Branding/Finance 相关 schema 与三个安装钩子单独完成。发布必须沿用现有窄范围元数据工具，不能把这个 migrate 记为通过。
- 全 Python 基线最初缺 pytest；补齐后曾因 QA 服务工作目录调整而被中断，尚未计入通过。最终需完整重跑。
- `bench build --app deeplinkerp_branding` 完成，带既有 Browserslist 数据过期提示；后续前端变更仍需重新构建与真实页面验收。

## 已确认问题：Finance 取消快照并非正确反向金额

已保存本地安全边界提交 `bcfe1ce3d7c0ca03d717b3b0a24bd2d12baa9af1`（9 个文件，新增 1,259 行、删除 104 行）。统一 Integration Request 操作边界替代三个入口的 Redis-only 幂等；新增标准控制器源锁、原生库存/财务及逐键中国冲销检查、独立运行日志。尚未完成该阶段的规格/质量审查，也未实现剩余批量、自动草稿或金蝶式列表任务，因此不作为发布候选。

主线程对该提交独立复验：

- 初始化隔离 Frappe 后 `pytest .../deeplinkerp_branding/tests -q -p no:cacheprovider`：`597 passed, 314 subtests passed in 52.06s`。
- `test_purchase_document_actions_qa.py` 新原子案例默认入口：8 项原生测试通过，3.548 秒；每项运行后核对恢复原记录计数。覆盖真实提交、库存/账务故障回滚、跨事务幂等、财务失败以及错误取消被拒绝；**不代表正确取消 happy path 已通过**。
- `git diff --check` 通过。原生 ERPNext 带既有 V16 弃用提示。未执行新界面验收、集成发布 CI 或本轮生产部署。

在对齐线上 Finance `4f019f91` 后，新增逐键冲销校验揭示原有服务问题：

- `china_finance/services/voucher.py:720` 创建 Cancellation 时调用 `get_gl_entries(cancelled=True)`。
- `:778–792` 仅过滤 `is_cancelled=1`，同时取到 ERPNext 标记取消的原 GL 和反向 GL。
- `:729–730` 只有无 GL 时才使用已有 `reverse_voucher_entries`，有原+反向 GL 时不会走正确的原凭证反向。
- 合成原生 PE 取消中，应付科目 Posting 净额为 `+10 CNY`，现金科目为 `-10 CNY`；取消快照两科目净额均为 `0`（本位币和科目币种相同），而不是 `-10 / +10`。来源链接、借贷平衡和服务返回 `resolved` 均不能证明正确冲销。

原先只验平衡/状态的取消 happy path 不再计为通过。新的采购边界保持逐键金额检查并整体回滚，不能在 Branding 内重建或改写中国凭证掩盖缺陷。正确取消的集成验收须先修中国财务服务；该源码不在本工作树。

已向唯一发布对话询问，对方确认没有 Finance 修复候选。对方另一个已批准的运营版本计划串行发布 Branding `00fee003b9cdbe8b43ee314406afa62487fc3b59`，仍保留 Finance `4f019f91`，该运营范围不提交/取消 PE、不产生 GL；并未包含本次采购改造。当前采购改造不部署，后续批量/同步/界面任务暂停，等待明确跨仓修复方向。

## 2026-10-08 授权补充与恢复

用户明确允许修复中国财务底层冲销服务，并进一步限定：**历史单据不处理，仅确保以后新发生的冲销正确**。不得运行历史回填、修复、清理脚本，也不以改写历史快照掩盖新校验失败。

唯一发布负责人已确认线上 Branding 为 `00fee003b9cdbe8b43ee314406afa62487fc3b59`，Finance 仍为 `4f019f91f36aa549df1854d2df0b60e20c01751c`。Finance 准确源码基线已找到，隔离修复工作树为 `/Users/smk/.codex/worktrees/finance-reversal/DeepLinkERP`，分支 `codex/finance-cancellation-forward`。不修改其他对话原有 Finance 工作树或线上容器。

复用既有 `reverse_voucher_entries` 从原 Posting 快照生成反向分录；不能把所有 `is_cancelled=1` 的原 GL 与反向 GL 一起当作冲销证据。没有可靠原快照时停止并保留明确待处理原因，不凭总账抵消后的零净额推断成功。后置校验必须比较科目、币种及维度对应的反向金额，不能只核对借贷平衡、链接和 `resolved` 状态。

当前先完成 Finance 修复及规格/质量审查、隔离原生控制器取消测试，再恢复采购阶段。采购事务边界审查发现的原生拒收数量口径及自动应付权限问题也必须修复，未经完整审查不得作为发布候选。所有生产发布仍交由已协调的单一负责人串行执行。

### 采购基础边界规格审查待修项

独立只读审查针对 `bcfe1ce3`，不把剩余批量/同步/界面当作本阶段完成。以下仍须回到原实现修复并复审：

1. 自动 PI 的真实创建/写入/提交权限及配置启用后的完整生成后置条件；不能继承既有自动钩子的 `ignore_permissions` 绕过当前用户。
2. PO/PR 已开票来源行与原生 `billed_amt/per_billed`；本次 PE 的真实 PLE 核销金额/引用和 PO 预付款，不能只看 PI 余额等于 PLE 汇总。
3. 原生表单丢响应后的稳定操作标识、完整内容绑定，以及重放时本次所有成功产物的现有状态与权限。
4. PR 拒收在原生 PO 已收数量中按 `received_qty`（合格加拒收）计算，不以仅合格的 `qty` 替代。
5. 原生 PO/PR 实际 Sales 来源与预留关联不能被当作“不适用”；复用原生服务，无法安全适配时明确拒绝。
6. 字段精度与 System Settings 原生舍入方法一致；Posting 中国快照来源/公司/事件完整；即使 rollback 本身失败也保留运行日志和原异常。

审查未运行数据库测试；已收口径与银行家舍入问题另用完全 mock 数据访问的纯函数复现。旧的 597/314/8 通过结果不覆盖以上缺口，不能据此发布采购边界。

不可变总账模式也须覆盖：ERPNext 此模式保留原 GL 和反向 GL 为 `is_cancelled=0`，不能简单拒绝所有仍有效的 GL 或因 `is_cancelled=1` 为空而跳过中国冲销检查。保留原生配置，按真实原账/反向账语义核对。

### Finance 前向修复阶段验证（不是整个采购计划完成）

- Finance 最终候选：`b73f17138fdf8235e91a687b8a113cbb33e7031c`，精确基线 `4f019f91`；3 文件新增 296 行、删除 33 行。其中业务源新增 81/删除 19 行，测试新增 209/删除 14 行，CHANGELOG 新增 6 行。新增 12 个业务测试方法及 25 个参数化子例；修改两个原本容许不可信取消 GL 的旧测试，没有新增并行冲销流程。
- 独立规格审查、质量审查均通过；实际 helper 只读探针也覆盖四列金额和会计维度，审查无必修问题。代码与 QA 的 `voucher.py` SHA256 均为 `3956eeb851212e210f6f9fddaaa2f380caa496845e6164bad3b395f3c5539f4d`；测试文件均为 `038d5f726fe84e7e825ed529cc1e87185979e496d36d59caac0915b80794f07d`。
- 主线程独立 Finance 取消专项：46 passed、25 subtests passed，1.76 秒；双会话并发专项：1 passed，2.09 秒。实现者另外运行既有受控科目更正关联测试：13 passed。
- 主线程此前新增 PR→PI→PE、PE→PI→PR 取消案例，默认 guarded QA 曾报 9 项通过，5.598 秒；对齐最终候选哈希后再次报 9 项通过，4.914 秒。**后续发现该脚本只设置 `frappe.flags.in_test=True`，而决定库存重估是否同步执行的顶层 `frappe.in_test` 仍为 False；库存取消留下 Queued Repost Item Valuation，旧后置检查遗漏它们。故这两次结果仅证明已检查的反向金额、数量及部分业务状态，不能证明整条库存估值原子联动成功。** 原记录计数核对没有覆盖 RIV，不得称完整恢复或生产等效完整 happy path。
- 主线程完整 Branding 后台测试重跑：597 passed、314 subtests passed，51.97 秒。它不覆盖前述独立审查缺口，也不是完整采购验收或 CI/部署通过。
- `git diff --check` 和源/测试语法通过。原生控制器仍带既有 V16 弃用提示。补充凭证准备测试因 QA 缺少其硬编码公司而跳过 41 项，不把跳过算作通过，也不为此次修复创建生产公司或修复历史。
- 兼容保留：`get_gl_entries(cancelled=...)` 保留只读历史查询参数，不再用于构造新取消快照；未知跨分支/外部脚本调用未清理。只有核实全体调用方并明确停止使用该只读兼容参数后才能删除，不虚构退出日期。Finance 原生异步取消政策未被改变，严格同事务采购保障仍待采购阶段完成。
- 未处理技术债：Frappe Currency 原生 Float 读写上限，以及已有中国凭证控制器/哈希的两位口径未重构。本次按原生读取金额比较，不额外截成页面两位小数；不承诺绕过原生控制器的极端 SQL 数值破坏均可检测。
- 未执行生产业务提交/取消、历史回填/修复/删除；未部署该 Finance 候选。完成审查后交给已协调负责人按既有串行机制发布，Branding 未完成候选不得混入。

### Finance CI 与发布门禁补充

- Finance [PR #11](https://github.com/yueweiit/DeepLinkERP/pull/11) 的 [CI run 37727908168](https://github.com/yueweiit/DeepLinkERP/actions/runs/37727908168) 已通过，实际 `headSha=b73f17138fdf8235e91a687b8a113cbb33e7031c`。安装原生夹具、重复迁移及资源构建和测试步骤均成功；应用测试日志为 195 项、跳过 68 项，跳过不计为通过。
- 唯一发布负责人再次指出现有独立 Finance 原生取消仍采用提交后异步补齐。该金额修复不能单独证明采购原子联动满足要求；已通知暂缓将其作为完整采购修复发布，等待采购严格边界补强及独立复审后统一串行交付。生产仍未实施本次修复。
- 原生表单稳定请求键复用现有表单扩展及原生 `savedocs` 包装器，通过 HTTP 参数和内部 flags 传递，不新增业务字段；其他单据入口保持原生行为。程序内部无显式稳定键的调用仅保证本次事务，不声称跨请求重试去重。

### 原生库存重估边界与待确认范围

- 真实 ERPNext 的 RIV 在生产提交后排队，执行器含内部 commit。不能在严格采购事务中直接调用该执行器，也不能启用全局测试标记制造同步成功。新检查须把需要未完成重估的动作整体拒绝并回滚；已有相关未完成重估只阻止新操作，不处理历史记录。
- 原实现者 27 项原生场景的旧通过报告同样遗漏 RIV，不能算完整采购原子验收。验收正在拆分为可以同步完成的非库存 PI/PE 取消，以及须明确拒绝的库存取消／改价重估场景；最终计数待独立复验。
- 已向用户提出范围选择：先完成严格保护并提示不支持，或另行授权改造 ERPNext 核心重估以支持同事务完成。尚未获得核心改造授权；不改核心、不部署，不把阻止操作表述为已实现全部取消能力。已将此更正同步给唯一发布负责人。

上述为当时的检查记录，后续用户提出并确认了以下狭义例外，替代此前待选择项；没有批准改写核心重算。

### 已确认的库存冲销分阶段例外

- 用户明确同意：仅确实需要库存重算的新采购取消显示“待库存重算 → 重算中 → 校验中 → 冲销完成”；失败显示“失败待处理”，前后端禁止基于未完成结果继续办理。原生 Cancelled 与最终冲销完成必须区分。普通应付、付款及其他保存/提交仍保持同事务，历史错账不处理。
- 设计规格：`docs/superpowers/specs/2026-10-08-purchase-reversal-progress-design.md`。复用当前 Integration Request 边界、采购链查询/抽屉/表单、原生 RIV 调度与中国冲销服务，不另建采购流程或库存执行器。
- 原子受理事务与后台重算是不同阶段；后台原生分块可能提交，失败不能承诺撤销已提交阶段。只有最终库存/GL/适用中国凭证均一致，完成状态和解除拦截才能同事务提交。
- 只读源码复查确认：裸 Skipped 不足以证明成功；原生 GL 子任务创建可能吞异常；重算可沿调拨/拆装/制造传播，临时受影响文件会被删除。必须保留可证明的依赖闭包并验证实际结果，不只轮询已有任务状态。
- 当前先完成既有安全补丁的红→绿测试和独立规格/质量复验，再按此规格开展新能力。最终需纳入完整采购候选、较新的 owner 基线与集成 CI；继续由既定唯一负责人串行发布，当前不部署。

### 暂停时的安全检查点

- 实现者在本轮最后一批报告 36 项测试、34 通过、2 errors、0 skip；新四列 GL 校验尚不兼容 CAV Document 子行，导致设置停用取消及不可变账簿取消提前报错。当前源码不能验收，原先同名用例通过不代表现在通过。此结果未由主线程重复运行。
- 当前修改保留在工作树，HEAD 仍为 `5fd416534ad2735e507414f4639407296d4fc5d2`；无本批冻结提交、推送、合并或部署。尚需修复两处报错、完整独立复验与规格/质量审查，不将失败关闭保护当作完整采购流程交付。
- 已要求实现者在当前测试自然清理完成后停止改代码、开启测试或提交；实现者确认 rollback/清理完成并释放 QA。主线程再次检查容器进程只剩两个原有 gunicorn，工作树修改及文档均保留，`git diff --check` 无错误。没有生产业务写入或历史处理。
- 主线程独立前端测试在本轮为 479 passed、0 failures/skips；它不能证明后台当前源码或完整采购计划通过。唯一发布负责人已收到继续 HOLD 通知，等待用户范围选择后再推进。

## 已批准书面规格后的执行分解

用户已明确批准 `2026-10-08-purchase-reversal-progress-design.md`，沿用既有实施和部署授权，不增加第二轮业务审批。上面的暂停段落仅保留审计历史，不代表现在仍等待授权。当前严格安全补漏、审查、异步扩展、剩余金蝶式采购任务依次执行；局部补丁不单独发布。

### Task 1A：冻结并独立复核严格安全边界

**Files:** 既有 `services/purchase_consistency.py`、`services/purchase_operation.py`、`services/purchase_document_actions.py`、采购表单桥、对应测试及 `deploy/local/test_purchase_document_actions_qa.py`。不改 ERPNext 核心、不实施新异步能力。

- [x] 冻结本轮五项补漏：合法零金额无 PLE；PO 真实 Bin 产物；MR/源 PI/履行关联及 Finance 真实产物；中国凭证日期/期间/反向关系；REST 取消通过删除旧采购引用逃出边界。随后追加 DN 及内部交易 Sales 关联识别/预写旧身份检查、直接付款草稿 replay 和非采购表单透传，最新冻结 `1ce76c0a`。
- [x] 在实际 `frappe.in_test=False` 的隔离库重跑原生脚本，并核对精确 fixture 清理、RIV 与账簿计数。命令：`docker exec -w /home/frappe/frappe-bench/sites dlp-kingdee-purchase-qa-backend-1 /home/frappe/frappe-bench/env/bin/python /workspace/deploy/local/test_purchase_document_actions_qa.py`。预期全部案例成功且计数恢复；不得用旧结果替代新提交证据。
- [x] 对冻结 SHA 作规格复审；规格通过后才作独立质量审查。重要问题回到同一实现者修复，重新测试和复审；最终 `1ce76c0a` 两轮通过。
- [x] 主线程独立重跑全部 Branding pytest、`node --test tests/*.test.js`、Python/JS 语法与 `git diff --check`。报告案例数、参数展开、跳过、现有告警，释放 QA 与 index 后进入 1B。

2026-10-08 当前冻结补漏为 `eb02a1107ca411135fd6d61b37614fd64b25e4d8`，4 文件 +486/-17（业务源、单测、原生脚本、局部规格），不包括本执行计划。主线程独立实际复验：native 完整脚本 51 tests / 39.223s / OK；Branding 615 passed、325 subtests passed / 53.26s；Node 479 passed、0 failed/skipped；Python 编译、JS 语法及 diff 检查成功。原生脚本保持顶层 `frappe.in_test=False`，每个 fixture 清理后原计数恢复，重跑后容器只剩两个原有 gunicorn。规格复审与其后的质量审查仍未完成，不将这些 green 结果认定为安全阶段或完整采购候选验收。旧委外 supplied Bin 的新增案例是 native-shaped 单测，不是旧委外全业务原生验收。零 GL 取消留下 Finance Pending issue 仍失败关闭，作为当前限制明确保留。

`eb02` 正式规格复审随后确认上述五项补漏，但仍为不通过：原生 inter-company Delivery Note→PR mapper 带入 `inter_company_reference/delivery_note_item`，PR 原生 updater 会改 DN Item.received_qty；现有 Sales 检查只检测 SO/Packed/reservation，遗漏该真实未适配来源并可能误报 N/A。源代码合法路径已确认，运行时成功提交尚未验证。交回原实现者独占 QA 做真实 red→green，最小识别并拒绝此未支持 Sales 来源，不扩展 Sales 同步或历史处理；修复后重复独立验证和规格复审，再进入质量审查。发布负责人已收到继续 HOLD 和未来旧 worker drain 门禁通知。

**DN 补漏后的新检查点（仍不是 Task 1A 验收）：** 冻结 `b030f656f73e784f4c1c34d36b812f6984c9d694`，4 文件 +82/-8；生产 guard 只新增 5 行，复用现有 source read/lock 与 Sales fail-closed，不新增 Sales writer。合法跨公司非库存 DN→PR 原生 mapper 的真实 red 已观察到 PR 提交且 DN Item.received_qty 从 0→2；新 guard 拒绝该真实未适配关系，并检查 PI/PE 经 PR 的同一来源 ACL。测试脚本前向加入 Item Price 的同次精确身份/计数清理，既有历史 QA 残留未删。

主线程对 `b030f656` 独立重跑：原生完整脚本 **52 tests / 36.747s / OK / exit 0**；全部 Branding **616 passed、331 subtests passed / 52.67s / exit 0**；Node **479 passed、0 failed/skipped / 397.821ms / exit 0**；四个 Python 源/脚本编译、采购表单 JS 语法、冻结范围及工作树 diff 检查均通过。每项原生 fixture 的 36 类受控计数恢复，含新增 Item Price；运行后仅两个原有 gunicorn。测试脚本 SHA256 `36063d1503607db6effea0948bad842bfe62961b2f57aa32dcee2e5e58929385`。

实现者此前一次原生方法全绿但 finally 报 `NameError: fra`、命令 exit 1，不计通过；host/container 文件与编译名核对后无修改重跑正常，原因未证实，未加 catch 掩盖。上述主线程独立运行也正常退出。新的正式规格复审进行中，其后独立质量复审尚未开始；不因 green 测试提前进入 1B、不部署局部提交。

`b030` 规格复审随后确认 DN 和原五项补漏，但仍不通过：未识别 PO 的 `inter_company_order_reference`、PI 的 `inter_company_invoice_reference/sales_invoice_item`。原生取消 `unlink_inter_company_doc` 会清除自身和对应 SO/SI 表头，取消后 fresh document 可能丢失该来源身份；必须在原生写入前或根据持久旧事实检测，不能事后误报 N/A。mapper 与相容采购来源的合法路径已源码确认，真实组合单据 red 尚待执行。继续交回同一 writer 有限复现、复用现有 Sales guard 识别并拒绝，不新增 Sales 适配或处理历史；当前 1A 尚未完成，不进入 1B。

**内部交易预写检查的新检查点：** 冻结 `ce985c3f670b9a7b1828dac333385c453240aba4`，4 文件 +153/-11，其中生产源 +12/-3；统一现有 PO/PR/PI Sales 字段映射，并通过现有 `_stage` 在原生写入前检查持久旧身份和 incoming 身份。实际 red 已证明：合法 SI→PI 加普通 PO 来源可保存并误报 Sales N/A；parent-only PO/PI 原生取消确实清除双方 SO/SI 表头。合成旧关联夹具仅在创建及 setup commit 时暂停应用 Sales guard，取消主体恢复真实 guard；native mapper、校验、unlink、Finance 不 mock。新增 3 个原生测试方法和 1 个单位边界方法，6 个新增参数展开；复用内部双方/价目夹具，没有新 Sales writer 或流程。

主线程对 `ce985c3f` 独立运行并确认 exit 0：原生完整 **55 tests / 39.751s / OK**，全部 Branding **617 passed、337 subtests passed / 53.12s**，Node **479 passed、0 failed/skipped / 378.945708ms**，四文件 Python 编译、JS 语法、冻结范围和工作树 diff 检查通过。每项 37 类受控计数及原生采购/Sales/Finance artifact 恢复，运行后仅两个原有 gunicorn；脚本 SHA256 `c413003811440c24726fa6fca1c3a425247cffdf53c6f8067172197dcb17d2eb`。旧 QA 价目残留不删除。正式规格复审仍进行中，独立质量审查尚未开始，不将此测试检查点当作 1A 通过或完整发布候选。

`ce985` 随后通过限定 Task1A 正式规格复审；其后的独立质量审查仍要求修复两项 Important，当前不能进入 1B：

1. 现有 whitelisted `purchase_payment_service.create_payment_draft` 的 replay 只读取当前 PE/权限与投影，遗漏已有 `replay_artifacts(previous)`；原请求键在草稿已被合法编辑后仍可返回 reused，未遵守新的完整证据绑定。须复用该校验并测试同一路由 unchanged/changed draft。
2. `purchase_consistency.savedocs/cancel` 包装器仅按 PI/PE doctype 判断，给非采购 PI、Customer/Operating PE 施加了采购后台提交限制/受理行为。须对 incoming 和 persisted old 都非采购的情形走原生 passthrough，不能因 incoming 清除旧采购引用就逃出保护；同时验证带/不带稳定键和原生 queue path。增加 UUID 参数本身不作为问题。

两项均已由主线程核对实际入口源码，交回同一 writer 作有限 red→green，不扩大非采购业务改造；之后重跑独立验证、规格和质量复审。以上 green 结果不覆盖这两条新缺口。

**两项质量补漏的新检查点：** `1ce76c0ad74c27ea658f424df1de3da6d60b2876`，5 个修改文件 +191/-11，无新增/删除文件。直接草稿 replay 调用已有 `replay_artifacts`；同一 form 分类 helper 检查 proposed 与 persisted 采购身份，未使用 `_current` 给无关单据增加 read ACL，清除旧来源或伪造 `__islocal` 不能逃离已有边界。3 个新增独立原生场景、1 个单位选路矩阵（32 个参数）；已有采购队列场景增加 4 个旧身份参数。

实现者实际 red 已观察到草稿两个合法编辑参数不拒绝旧回执、4 个非采购队列参数被误拒、2 个 keyed Save 产生采购审计、2 个 keyed Cancel 被要求快照。首轮完整 native 58 exit 1 的四个队列失败另为夹具 scheduler alias 提前导入造成；仅补受控夹具 native save 模块与 wrapper 的两个真实 alias，不改变公司/调度配置。Queue 插入和状态保持原生，仅隔离外部 `queue_action` dispatch。该失败轮不算通过。

主线程对同一冻结 SHA 独立重跑并确认 exit 0：native **58 tests / 47.709s / OK**；全部 Branding **618 passed、369 subtests passed / 53.67s**；Node **479 passed、0 failed/skipped / 457.558875ms**；四文件 Python 编译、JS 语法及冻结范围/工作树 diff 检查通过。脚本 SHA256 `e5141b81ef76fb3148ef523819677032fe8ddf13565050016f0e8a0ce3a698cc` 与容器一致，Finance voucher 仍为固定候选 `3956eeb851212e210f6f9fddaaa2f380caa496845e6164bad3b395f3c5539f4d`。所有 fixture 的 37 类计数核对成功；完整测试后再次只读查询 37 类，PO139、PR114、PI5、PE6、GL16、PLE8、Bin306、CAV8、SyncIssue19，IR/SubmissionQueue/RIV/SLE/新 Sales/DN 均 0，顶层 `frappe.in_test=False`；仅两个原有 gunicorn。正式规格复审已通过，随后的独立质量复审进行中，尚不标记 1A 完成或进入 1B。

随后同一冻结 `1ce76c0a` 独立质量复审通过，两个 Important 均关闭，无剩余 Critical/Important 或可行动 Minor。只批准限定 Task 1A 进入 1B1，未批准完整候选发布。主线程停止全部 QA 活动、保持原生脚本结果和退出证据，串行交接下个 writer。继续保留严格 RIV、未适配 Sales/Operating、零 GL Finance Pending 限制；新 async、批量、来源同步、UI、集成 CI/browser 和统一部署均未完成。

### Task 1B：范围、元数据与跨 commit 锁协议（先不放开取消）

执行时分为两个连续审查的小步骤，沿用下面的同一契约，不建立平行服务或增加业务审批：

- **1B1 闭包与窄元数据：** 只实现 `purchase_reversal_scope.py` 的完整、有界原生范围收集、`purchase_reversal_install.py` 的可重复元数据安装及其已有 QA 夹具测试。验证取消种子、同时间未来行、调拨/拆装/制造传播、原生 GL 的 item 集合 × warehouse 集合与 whole-voucher 影响，以及来源替换/权限/超限。安装钩子可注册但没有启用异步取消、运行后台任务或给业务写入豁免。普通首笔库存草稿缺少 Bin 不应被取消冻结规则误拦。
- **1B2 会话 lease 与统一入口：** 在 1B1 冻结、独立规格和质量审查通过后，实现 `purchase_repost_boundary.py` 的物理连接握手/锁生命周期、指针保护及原生 `_save/insert` 的旧/新范围拦截，运行真实两连接和入口覆盖测试。只有两个步骤均通过才能完成 Task 1B，之后进入 worker 隔离 Task 1C。

**1B1 首次冻结未通过（2026-10-08）：** `2252f49b19470fa97204f3b4dec898e4f11aae1f`，8 文件 +1217/-19。正式规格复审指出三项必要修复：SLE pair 必须绑定对应真实明细而非整单集合；Stock Entry 直接/在途 MR、旧委外 PO 与 reserve Bin 的真实来源不能静默遗漏；启用发票价成本调整时，非库存 PI 的真实 PR 重贴种子和最早时间不能遗漏。仍未进入质量审查、1B2 或部署。

主线程独立复验此冻结：native 63 methods / 44.852s / exit 1，唯一失败为既有 System Settings 舍入夹具，另 62 方法通过；Branding 651 passed、398 subtests / 50.44s / exit 0；Node 479 passed、0 failed/skipped / 381.553834ms / exit 0；7 文件 Python 编译、冻结范围和工作树 diff 检查通过。脚本 SHA256 `fafaedb48df0d8a1da941bcbca6cdbd0626a0a2e73b85df729e996b774f83bc5`。38 类业务计数均恢复，六类新元数据指针全空、索引和定义准确；scheduler_disabled=True、enable_scheduler=0、frappe.in_test=False，探测结束后仅两原有 gunicorn。

主线程对舍入失败完成原生受控证据：实际持有 ClientCache 的锁阻塞异步失效，数据库已为 Commercial Rounding 而进程缓存仍为 Banker's Rounding，原生 `.0025` 得 `.002`；调用原生 `clear_system_settings_cache` 和 document cache 失效后为 `.003`。只允许修测试夹具的同步缓存失效及 rollback 清理，不修改业务 rounding 算法、不以重复运行绿结果掩盖首轮失败。主线程已关闭全部 QA/探测，交回同一实现者修复三项规格缺口与该夹具，再重新冻结和独立复验。

**1B1 第二次冻结独立检查点（2026-10-08，限定 B1 已验收）：** `451fda9e0c673bb24bab4f709fbd935988482f30`，本次修复 4 文件 +545/-85，累计相对 `d72c12a...` 8 文件 +1691/-33，无删除文件。正式规格复审限定 B1 通过：按实际 detail 绑定 pair、直接/在途 MR 与真实旧 PO supplied `stock_uom`/reserve Bin、PI 原生 IF-pr-detail/ELSE-po-detail 的 potential PR seeds 均关闭；正向 Manufacture FG 的实际 `recalculate_rate` 也在未适配消费成本来源处拒绝。未启用异步取消，不将 potential PR 说成实际 RIV 根。

主线程 fresh native 66 methods / 54.156s / exit 0；Branding 663 passed + 432 subtests / 53.99s / exit 0；Node 479 passed、0 failed/skipped / 594.258667ms / exit 0；7 文件 Python 编译与冻结范围 diff 检查 exit 0。QA 脚本 SHA256 `6876b06ba78f82916569aac6240964cf202867a3ecd80551aabe5776e29a7b03`；Finance voucher SHA256 `3956eeb851212e210f6f9fddaaa2f380caa496845e6164bad3b395f3c5539f4d` 未变。隔离 site/database/host 精确防护的只读后检确认 38 类计数恢复（Custom Field133 为原127+exact6元数据、ItemPrice515历史不动），六类指针全空、定义/物理列/非 virtual/唯一单列索引准确，`frappe.in_test=False`、enable_scheduler0、原生 scheduler_disabled=True。所有 QA/probe 退出，docker top 仅两个原 gunicorn。正式质量复审无剩余 Critical/Important/可行动 Minor，主线程据源码、两正式只读审查及 fresh 执行证据接受限定 B1。尚未交付 1B2/worker/最终对账/UI/CI/browser/deploy，也不称整体采购流程完成。

原生闭包须合并真实 stock propagation 与 GL propagation：根凭证的 raw SLE 包含取消行；未来库存行使用原生时间比较和依赖 detail 引用；GL 查询使用原生 item 集合 × warehouse 集合，而不是仅原始 pair。查到的真实凭证须纳入其全部实际行和相关来源。原生按 voucher name 排序造成跨 doctype 同名扩张时，纳入完整真实身份或明确拒绝碰撞，不静默漏算。任何无法验证的公司/仓库/来源/控制器路径在业务写入前失败关闭；不得借 UI 100 条限制、忽略 read 权限或截断查询伪装完整闭包。

1B1 的原生阶段复核进一步限定固定点算法：**库存传播 frontier 与整单保护/证据 footprint 分开**。库存 frontier 只由根 raw SLE、原生未来 pair 扫描、实际 dependency detail 和 repack incoming 路径扩展；每条新 pair 使用实际传播 SLE 的时间，并保留已知更早 anchor。GL 候选合并根任务原生 direct Cartesian selector 与库存阶段可能受影响的 typed transactions。原生 `repost_only_accounting_ledgers` Transaction 子任务只处理自身一个 voucher，不再调用 direct selector；因此不能因一个 GL-only 子任务或整单额外行而递归播种新的 stock/Cartesian 查询。它们的全部真实行、pair 和来源仍加入保护及最终证据集合。source-only PO/MR/nonstock PI 的真实 Bin 影响可加入 footprint，但不凭空播种估值传播。重复到原生 stock frontier 和真实来源身份不再增长，而不是迭代一个扩大到无关业务的 GL 传染图。

1B1 的 `collect_cancellation_scope` 根只允许本次采购范围的 PO/PR/PI/PE；SE/DN/stock SI/Stock Reconciliation 是已核对的实际依赖身份，不授权新增根取消业务。LCV 的 `collect_document_scope` 读取其真实 PR/stock PI/SE 来源 footprint，但本轮不假称已实现 LCV 自身取消触发各来源重贴的完整闭包，取消根明确拒绝。后续原生 worker 若需其它实际 RIV 范围，沿同一内部收集器复用已验证原生种子，不能建立第二套传播算法。安装器对已有兼容指针字段同时预检非 virtual 及真实 SQL 列；缺列只停止，不覆盖/修复现有定义。

**Files:**

- Create: `deeplinkerp_branding/services/purchase_reversal_scope.py`：闭包、旧/新范围、持久指针和业务拦截。
- Create: `deeplinkerp_branding/services/purchase_repost_boundary.py`：物理数据库会话锁、原生 worker 身份和扩展适配；不包含重算算法。
- Create: `deeplinkerp_branding/purchase_reversal_install.py`：可重复窄范围 schema 安装，不回填业务数据。
- Modify: `deeplinkerp_branding/hooks.py`、现有 `ProcurementControllerBoundary`，保留其他应用扩展和钩子。
- Test: `deeplinkerp_branding/tests/test_purchase_reversal_scope.py`、`test_purchase_repost_boundary.py`；扩展既有隔离原生测试夹具，不能复制既有取消案例。

**固定契约：** 范围由公司、真实来源身份、真实物料/仓库对、受影响库存凭证身份、最早生效时间组成；排序去重。只允许存在且属于该公司的非分组仓和真实 Bin。范围查询上限为 2,500 对、5,000 凭证、50,000 SLE；超限在写业务单据前拒绝，不能截断结果再称闭包完整。

```python
from dataclasses import dataclass

@dataclass(frozen=True, order=True)
class StockPair:
    item_code: str
    warehouse: str

@dataclass(frozen=True, order=True)
class DocumentIdentity:
    doctype: str
    name: str

@dataclass(frozen=True)
class ReversalScope:
    company: str
    posting_datetime: str
    pairs: tuple[StockPair, ...]
    sources: tuple[DocumentIdentity, ...]
    vouchers: tuple[DocumentIdentity, ...]
```

- [ ] 先写真实图案例：取消前收货 → 调拨 → 拆装/制造 → 另一物料/仓库未来凭证；以及独立公司/范围。核对原生 `_get_directly_dependent_vouchers` 的 item 集合 × warehouse 集合查询，不能只沿原始配对。测试必须对完整集合断言，包含超限拒绝、不存在 Bin、跨公司与换来源。先看到预期失败，再实现闭包。
- [ ] 先写两连接锁案例：同一范围互斥、无关范围通过、commit 后仍持锁、rollback/异常清理、同会话重入、物理连接断开禁止继续写。使用同一实际业务连接的 MariaDB `GET_LOCK/IS_USED_LOCK/RELEASE_LOCK`，锁名采用站点/数据库/规范身份的摘要并按稳定顺序取得；不能用独立“只持锁”连接或 Redis 作为权威。
- [ ] 非阻塞取得整个锁集；失败释放本次新取得的锁并拒绝/保留原生 pending。锁仍覆盖执行和去重；active lease 跨原生 commit 保留，结束后的 dormant lease 到实际 commit/rollback 才释放。CallbackManager 会持续消费队列，回调不得在自身内部重新加入自己；下一个边界重新注册。物理连接替换毒化当前执行，不在同一上下文重新取锁继续写。
- [ ] 实际原生 `Database.commit` 在 `before_commit.run` 前先清空两个 rollback 队列；更早 before_commit 抛错会让 lease 自己的回调尚未运行，其原 after_rollback 又已丢失。回滚也先清空 commit 队列。清理必须有不依赖该回调已经运行的真实事务/执行边界路径；用两连接覆盖先于/后于本应用回调的失败、before_rollback 失败及 savepoint rollback（不释放外层 lease），不只测 mock callback 列表。现有 QA `commit_fixture` 会 reset after_commit，不能在被测 lease 后清空释放回调再称时序已通过。
- [ ] 实际 SQL commit 与原 wrapper 返回分开证明：after_commit callback 可能产生下一事务的新业务写入/lease，不能在上一个 commit 返回时释放这些新 dormant lease。after_commit 报错也可能已经提交，不声称全部回滚。before_rollback 报错且实际 SQL rollback 尚未执行时，不能释放锁而留下未提交业务；验证同物理连接的 rollback/close 清理后果并保留原错误。原生 RIV 在内部 rollback 后继续写 error/status、finally commit；active 执行隔离不能因内部 rollback 提前解除，除非毒化并停止全部后续写入。
- [ ] 原生 before_commit/before_rollback callback 内嵌套事务边界不能冒充外层调用自身 SQL 已完成；使用每次事务调用身份和原 callback phase 的窄观测区分，保留原队列及执行算法。真实两连接验证 nested rollback 后的新业务写入仍在外层失败时清理；物理 fallback 同时遵守 full rollback 的 commit-callback reset，原已回滚业务的 after_commit 不得在后续 native status commit 执行。rollback callback 无法安全完成时毒化/关闭并禁止续写，保留第一异常，不凭全局 epoch 变化或最终请求清理宣称原子性。
- [ ] 取得 lease 后用真实 current/locking read 重新核对来源、SLE 和 scope，而不是重复 REPEATABLE READ 下的旧快照；覆盖“另一事务在初次只读范围计算后、取得 lease 前已提交调拨/新增来源”的两连接场景。必要范围扩展按同一有界收集器处理或明确拒绝重试，不能以旧范围放行。不得在审计/业务已写入后 rollback 只为刷新快照，也不改变数据库全局隔离级别。
- [ ] 当前已核查的 mysqlclient 2.2.7 使用真实 `_conn.ping(False)` 在该连接任何业务/审计写入或 lease 前禁用 C 层重连；它可能隐式 rollback，不能放在 chunk 中间或已执行 `_reserve` 后。将握手放在最外层请求/job/内部操作初始化，记录连接物理对象和 `CONNECTION_ID()`，故障注入证明断开不会换连接写入。未知 adapter 不放行 async。相关主源：[mysqlclient C 实现](https://github.com/PyMySQL/mysqlclient/blob/v2.2.7/src/MySQLdb/_mysql.c#L1784-L1846)、[MariaDB 会话锁](https://mariadb.com/docs/server/reference/sql-functions/secondary-functions/miscellaneous-functions/get_lock)。
- [ ] 全局 before_request/before_job 不得把未核查 adapter 的无关普通请求一律拒绝；只对已核查 mysqlclient 类型早初始化，未知类型不强制连接、不授权 lease/async。真正保护的采购/stock boundary 仍在审计、行锁和业务写入前严格拒绝未核查物理能力；测试未知普通路径透传及受保护路径提前拒绝，不通过 flags/duck typing降低授权证明。
- [ ] 公共入口也必须早于其已有行锁初始化握手：未 keyed 的 `update_payment_draft` 和 `submit_document(Payment Entry/其他目标)` 先 `_locked` 或 `_locked_source`，来源 PO 的 `create/associate` 先 `_source(for_update=True)`。请求初始化与已连接的新内部执行上下文复用同一初始化；深层 `run/insert/_save` 仅验证既有物理身份，不能在持锁后首次 ping 或在原生 commit 后重握手。待真实原生请求/callback 时序核对后实现，不将 host 预审当作执行证据。
- [ ] 补充实际请求/退出源码证据：Frappe `HTTPRequest` 在 `before_request` 前创建/恢复 Session，登录分支已写 Session/User 并原生 commit；不能称 before_request 是全请求第一条数据库写入。区分原生会话维护与本计划业务/审计写入，核查之前的登录钩子和 hook 顺序；任何可进入采购业务的早期路径必须在其写入/行锁前握手或明确拒绝。真实 `frappe.destroy` 直接调用 `db.close` 后释放 local，没有事务 callback；close/KILL/物理替换清理与毒化必须据此测试，不假设 after_rollback 自动触发。主线程只读副本 `/tmp/dlp-b2-request-native.bAiTcG` 的 `__init__.py` SHA `018ed9b4c3a50f0f5682f46310255d60e452e8c88a63055a3e70f659ba706db6`、`auth.py` SHA `30783d5da46d0b6f2cfc1cede2b6de15463c3a173cbdf88e998801979462309d`、`sessions.py` SHA `fb1708255852cedcfcdd7d1661b646310ad3cb034401733d0681b094eaf55ae1` 仅为设计核查，不是 B2 运行验收。
- [ ] schema 只增加 `custom_purchase_reversal_operation` 隐藏、只读、no-copy、有索引的 Integration Request Link：Bin、实际 PO/PR/PI/PE 来源、实际 owned Repost Item Valuation generation。RIV 指针支持终态保护和保留，不扫描全部 IR JSON 代替身份索引。指针不改变库存量、金额或历史凭证。保护普通表单/API 的指针改写；安装重复执行不覆盖现有定义，不创建 Bin、不导入历史资料。
- [ ] 扩展最外层 `_save/insert` 范围检查，早于原生 `check_if_latest` 和控制器业务写入；不能只依赖 before_validate（取消会跳过），也不能只用 SLE 钩子（原生取消先执行 raw SQL）。覆盖实际 stock 控制器 Stock Entry、Delivery Note、stock Sales Invoice、Stock Reconciliation、Landed Cost Voucher 的旧/新范围；PI/PE 沿真实采购引用取范围。未实现的真实关联路径明确拒绝，不伪造“不适用”。
- [ ] B1 root lifecycle 的 WO/JC/Project 等未知路径不能不加区分套在全部 SE 上，造成零 pending 时普通制造也永久不可用。允许显式保守 gate/read mode：已核查路径保持 pair 级 lease；未知 lifecycle 仅在权威 fence 下证明其真实 company domain 无 pending 后原生透传，有 pending/无法证明则明确拒绝未知交集。company domain 必须据原生校验及真实来源/仓库证明，不能仅信 incoming company；无法界定跨 company 时须足以覆盖的 site fence/absence 证明或拒绝。后续 D 受理/最终解锁须取得同一 fence，稳定顺序 fence→pair/source，未知路径保持到实际最外层事务结束。真实两连接验证登记互斥、完成后恢复和多公司边界。源/Bin pending 与 RIV 完成 generation 的永久指针不同，不能把 RIV 指针全空当 pending absence，也不能借裸 IR Completed 给异步权限；此阶段仍不放开取消。暂缓的未知路径是明确兼容限制，不声称已适配全制造。
- [ ] 普通 Material Request 自身可修改实际 requested Bin，不能只在 PO/PR/SE 读取来源时检查它。保留现有 MES performance mixin 和普通原生路径，按真实旧/新 stock pairs 及必要实际 PO/PR backlink 检查 pending gate；MR 不新增第七类指针，也不扫描全量 IR JSON。实际 MES 分支在未验证其异步适配前仍明确拒绝进入新异步取消范围。
- [ ] 固定原生源码已确认普通状态 RPC 绕过 `_save`：MR `update_status` 先 raw 写状态再 requested Bin；PO 同方法更新 requested/ordered/reserved/subcontract/blanket，bulk close 的部分分支即使跳过状态方法仍更新 blanket；PR `update_status` raw 写状态。复用同一最外层 document/batch boundary 和真实原生方法，不复制数量算法，保留 MES MRO。批量旧/新及 fresh 范围共享一个联合预算、全部校验后才写；任何 pending 或真实未适配依赖失败则整批无单边写入。状态联动的实际后置证据和操作审计不能由“持锁成功”替代。PI 的原生纯 hold/release 和其他直接内部 alias 必须列明能力覆盖，未核查不声称全部入口已保护。
- [ ] 原生 `AccountsController.update_child_qty_rate` 的 PO 分支会先删除/保存子行及更新来源/Bin，之后才 parent.save；须在该真实改量/改价函数第一笔业务写入前借用同一 boundary，并核实已有 docname 的实际 parent/detail 属于本 PO。无纯范围证据的新物料/晚推仓库按既定 opaque 门禁处理，不复制原生税费、UOM、默认填充或删除算法。非 PO 的原生 Sales/Quotation 调用透传，PO 动作继续共享 Task1A 后置校验、审计与整请求 rollback；新增状态/hold/改价专项需真实 RED→GREEN，不能用只测 parent.save 替代。
- [ ] MES 来源分类不等于实际 deferred writer：原生 mixin 仅由服务器 `flags.mes_integration_request` 进入异步 Bin 同步；来源字段及旧名称还可走普通原生分支。零 pending 的已有 MES 流程保持兼容，不以未核查异步为由全局禁用；尚未隔离已有 queued/fallback writer 时 D 继续关闭，不将 B2 普通入口检查称为后台全面覆盖。
- [ ] 比例验证普通新草稿兼容：原生 insert 在 wrapper 后才填部分默认日期/公司；如需在最早业务边界前补齐只读 scope 输入，复用经源码核查的原生、纯内存默认填充，不自行猜公司/库位，不运行业务计算或命名序列写入。真实最小 native 新单和首次库存无 Bin 场景必须继续可用；既有来源缺失或单位不明不能假称已验证。
- [ ] 用实际 REST/controller 证明来源/仓库替换、客户端 flags、ignore_permissions 不逃逸；相交 pending 指针拒绝，无关范围仍正常。尚不允许任何新异步取消：当前 strict RIV 拒绝保持生效。
- [ ] 在初始化 Frappe 的隔离测试环境运行两个新测试模块和原生完整脚本，保存红/绿结果；冻结此任务，规格通过后质量复审，再进入 1C。

**1B2 回归中间记录（尚未冻结或验收）：** 实现者首轮完整原生回归为 88 methods / 98.940s / exit 1，2 failures、6 errors；不计通过。原因核查包括原生 `savedocs` 清除新 local parent name 后、insert 尚未执行纯 `set_parent_in_children` 的早期副本，以及成功独立请求之间未提交的测试夹具。修复必须限于证明未落库的新副本和真实成功请求的夹具边界；生产失败的完整 rollback 不能关闭。已批准保留非库存 PI 草稿对真实 PR 草稿的只读保护引用，仍核对来源明细、Item/UOM、公司、供应商和权限；提交/取消、stock PI 与公开 B1 来源规则不放宽。同 link 的 OA `_bind` 虽不 save PO，但会写来源版本/确认状态，须在该写入前借用同一 document boundary。以上为源码核查及实现者专项报告，主线程尚未独立运行当前完整测试；C/D/UI/CI/browser/deploy 继续关闭。

补充实现者报告：PO 改量 pending 的真实 RED 已发生原生 child 删除/校验入口一次，随后才被 parent.save 门禁拒绝；wrong-parent RED 则先删目标、后在 items MandatoryError 失败，两者均非提前保护。修复后五项专项 5.559s、完整原生 94 methods / 105.488s 均 exit 0，但尚未冻结、主线程未复验。实际 workflow 的 pytest 不初始化站点；a126 与当前候选须同环境、独立进程、真实 import 路径和源码 hash 对照，不能只切测试目录却导入 editable 的当前包。前阶段本地通过不等于 CI 通过，基线相同失败不计通过；完整候选仍须解决本任务引入的既有失败并通过实际 CI。

**1B2 首次冻结规格审查：** `d1c43dcee50a4704b10ceee84ce9a75ec6679a1b` 为有限 B2 SPEC FAIL，尚未质量审查或主线程复验。确定缺陷是普通 insert 用旧名字读到同值 owner 后，原生 `set_name`/hash naming 更换持久身份，能把 RIV 的系统指针复制到新单据。必须在最早 insert 及原生 `_save` 的 local/no-name 分支、审计预留之前拒绝新身份的非空指针，保留真实旧范围检查；补真实 native/RPC RED→GREEN，不以 no-copy 元数据代替 API 保护。PI hold/release 尚需第二／第三次原生 db_set 故障的整请求回滚实测。正式审查只是源码证据，不称已执行漏洞复现。实现者冻结的 95 native methods、690 initialized pytest 与 479 Node 仅是整改前报告；site-free 的 83 failures 仍是完整发布阻断。

**1B2 整改中间记录：** 实现者提交 `0df8597195b3bfdb2a67a0d9a3ca74909f8325d7`，以四种真实新 RIV 身份的 RED 复现上述漏洞；报告窄修后完整 native 96 methods/145 subtests、initialized Branding 691/451、Node 479 通过。PI 第二／第三次原生写入及 release 已写后的四参数故障证明报告通过，未新增 PI 生产算法。无站点完整入口仍 83 failures，尚未正式规格／质量／主线程复验。最后自审提出 numeric `0`/`False` 被 truthiness 当空的指针疑点；主线程已授权只扩展同一真实矩阵先验证再窄修，不将未复现疑点写成已确认缺陷。正式复审等待新冻结；不进入 C/D 或部署。

该 numeric 疑点随后得到真实 RED 证实：`/tmp/dlp-b2-falsy-pointer-both-red.log` 中新 RIV 两参数和六类型未 owned 的普通 RPC/native save 共 26 次实际保存 varchar `'0'`；现有 db_set 十二参数已提前拒绝。统一空值定义只承认 None/空串，不以 truthiness 允许新身份或同身份改写。日志额外取消事实异常需定位并保留，不把 RED 的 26 failures/11 errors 报成单一干净失败；完整 GREEN、正式复审和主线程复验仍待执行。

额外取消异常的实际 observer `/tmp/dlp-b2-falsy-amend-diagnostic.log` 证实唯一业务表示差异是 Time：incoming `00:11:19.458673` 与 MariaDB timedelta `0:11:19.458673`。原生 Document.has_value_changed 已用 get_timedelta 比较同一事实；现事实 guard 的逐字字符串比较在午夜错误拒绝正常取消。主线程授权只对真实 Time 元数据复用该原生规范化，保留微秒／duration、非法非空值失败关闭和 child 递归；真实变更及 Text/金额/来源仍拒绝。须先补确定的夜间表示 RED 再修，不用重新加载夹具掩盖生产问题；本次可额外修改原 consistency tests，无广泛字段转换或历史修复。

**1B2 第三次冻结与规格复审（2026-10-09，仍未验收）：** `fd953aabe8e574fa33bf296b29664609cc0fe41c` 五文件 +198/-66，关闭 numeric 新／旧身份指针漏洞及真实 Time 表示误拒。主线程读取并核对实现者交接摘要 SHA `b0c606108811aa24b858e5428ae327212df203e5afca7df56b4525466b53b384` 和实际日志：native 96 methods/203 subtests、initialized 692/483、Node 479 通过；无站点仍 83 failures，与前一冻结失败集相同，不是 CI 通过。主线程尚未独立重跑这轮候选。

随后正式 HOST 只读规格审查发现一项 P1：当前 `Session.install.sql` 仅按 SQL 文本结束 epoch；固定原生 `Database.sql` 对 `run=False` 或 `explain=True` 提前返回，不执行 COMMIT/ROLLBACK，但 wrapper 仍真实 RELEASE_LOCK 释放 dormant 租约。主线程独立读取两者确认合法 API 路径，尚未称实际生产已触发；复审判定 FAIL，未进入质量审查。下一步复用原有 unit／两连接 native 矩阵，先实际 RED，再仅修原生不执行参数与 epoch 观测，保留真实事务、callback、KILL 和首异常行为；不可绕过这项审查直接进入 CI/C1 或部署。对 late handshake 的 row-lock/savepoint 计数疑点尚无 protected 生产路径证据，未列为第二项已确认缺陷。

**1B2 最终限定验收（2026-10-09）：** `292c25034f6be2cab7a707665aad9535fd73d28e` 关闭上述 preview P1，新增 3 文件 +98/-7 的窄修；没有第二套锁／取消／估值流程。实际 RED 已证明八个 COMMIT/ROLLBACK 预览放锁但未提交，另 BEGIN/DDL 误拒或污染状态；GREEN 扩展同一两连接原生场景及一个 unit 方法。正式独立规格复审、随后新独立质量审查均通过，限定 B2 无剩余 Critical/Important/可行动 Minor。累计相对已验收 B1 `a126c704` 为 15 文件 +2861/-79：业务/hooks +1159/-56、unit +490/-2、既有 Native QA +1212/-21，两个新增文件、十三修改、零删除；Native 独立方法 66→96，preview 窄修只展开 22 Native 参数和 34 unit 参数，没有复制测试框架。

主线程随后对同一冻结源独立执行并读取完整结果：`/tmp/dlp-b2-root-292c-native.log` **96 methods/225 subtests/116.025s/exit0**；`...-branding.log` **693 passed/517 subtests/49.30s/exit0**；`...-node.log` **479 passed、0 failure/skip/343.889416ms/exit0**；十五文件 Python 编译、冻结范围及工作树 diff 检查 exit0。boundary SHA `f7784aa53b2607d2d7c83dac804f5fc146c8b6b4bf000609190de23bd77fa089`、Native QA `5bc1bb9dad4f8815c8d14596df86d0ada687cc5af7ecd99f255bc75e17af21af` 与容器实际文件一致；Finance `3956eeb...`、MES `73cd5eb...` 和 native SQL `4ac73f...` 未变化。

主线程实际无站点入口 `...-sitefree.log` 为 **83 failed/662 passed/462 subtests/50.28s/exit1**，initialized=false、真实 import 文件路径和哈希已记录；83 个 failure 身份／顺序及 E 行计数与实现者最终日志精确一致，两个 diff exit0。该结果仍是完整 CI／发布阻断，不作为通过；下一独立步骤 1B2-CI 必须解决实际夹具缺口后才进入 C1。最初 Native observer 签名丢失导致的三项失败和只读 pycache 失败保留在交接日志，没有重写成首次绿色。

主线程独立只读 `...-proof.log` exit0：44 类计数全恢复，另 User Permission3 未变；六指针均0、没有 MR 第七字段，完整 SHOW INDEX 验证每个索引为实际字段的 nonunique 单列／seq1／无前缀 BTREE，物理列 varchar140、utf8mb4_unicode_ci、可空，元数据均 hidden/read-only/no-copy 非 virtual LinkIR；十二控制器 MRO 保留 MES mixin。frappe.in_test=False、enable_scheduler0、原生 inactive=True（config scheduler_disabled/pause 均 null，未冒称 true）。所有 QA session 已结束，仅原 gunicorn90965/90993。已接受的是有限 B2 基础，不是 worker、async、batch、UI/browser 或部署；WRITE-without-READ 的特殊角色兼容尚无真实 native 证据，保留为明确验证边界，不虚构此配置已通过。

### 2026-10-09 Vultr 当前版本只读复核

唯一发布负责人按本对话已授权的直接协调，实际只读核验六个服务同镜像 `deeplinkerp-custom:unified-purchase-00fee003b9cd`、image ID `sha256:cadd99c57288aa588f098f78aa9a20405ebac5b320679e605be57ffa3f7b4bf2`。Branding release label `00fee003b9cdbe8b43ee314406afa62487fc3b59`，Finance label `4f019f91f36aa549df1854d2df0b60e20c01751c`；容器不含 `.git`，标签不是实际分支／Git HEAD 证明。当前采购候选和 Finance 前向修复均未部署。

实际 runtime 为 Frappe/ERPNext 16.23.0、Python 3.14.2、mysqlclient 2.2.7、RQ 2.6.1、PyPika 0.48.9。native RIV `c4449547d07c76fd316a5b2185d4c9b60bd42e8747767fe28aea28cbc2ceafe1`、background_jobs `7db969deeb19e4a49924c2a59bcdc15e470a3d24d718845ea790fffd94046f45`、ScheduledJobType `80fbb163946521e1413d4ffa6fc8b777d003ee822ba420b4af6b84a47e4875ac`、File `5ce8960e8050798df73cfb70abf9409628e174cae9124f0c9c08ad55322cfabb`、file_manager `8ebd6f5169b6673c08399dfd81ad4e11be592b474051a7d803275efd9b38422f` 与固定本地源码一致。MES `73cd5eb8d391b53383fd6512b8665bf32bf4604754aa2c43f9d7ffd3d87f255a` 相同，线上 Finance voucher 仍是 `bf91a573a920cabb810161cd893d78fdc4044d760611b6fc43522986ef43038e`，不同于未发布候选 `3956eeb...`。这些是镜像及容器磁盘源码证据，不证明既有 worker 内存已加载未来候选 hooks。

协调回执 turn `01a11c5b-1413-79a2-b32b-daff136cab77`；没有 deploy/migrate/cache clear/restart/数据库写入。唯一发布负责人继续 HOLD，后续完整候选通过门禁后仍串行交付。

### Task 1B2-CI：完整无站点测试入口的夹具修复

在 B2 整改、规格/质量和主线程原生复验后，进入本独立测试步骤，再进入 C1；不把 initialized 通过替代实际 workflow。只复用现有 test setup/document factory/request fixture，不修改生产算法或安装额外生产 app 来消除单元测试失败。

**固定只读诊断：** `/tmp/dlp-b2-wip-provenance-final.log` 的 83 条为 31 FAILED + 52 SUBFAILED、37 个方法；六族为未绑定 DB/遗漏 finance assignment 夹具 34、native throw 消息状态 19、缺 response/message_log 16、GL 维度 metadata 5、直接构造站点 controller 5、四个未抛异常断言 4。前五族是日志已确认的无站点依赖缺口；主线程已核查 installed data.py SHA `d415013e661051e73a8d46fca9ce3b200f5dd6af0fabfb945f5a7f86db4373ae`：默认 policy 查询抛错时，flt 除 InvalidRoundingMethod 外返回零，能解释四个差异被抹平的断言，但仍需同 runtime 最小实测确认，不预断为 production bug 或已修复。当前 Docker 带 China Finance，workflow 只装 ERPNext/Branding，两个字符串 patch 还需用已有 optional-module seam 证明清洁环境可导入。

- [x] 先在未 frappe.init 的实际 bench 进程复现既有失败，保留真实 import 路径/hash；读取 installed flt/rounded，并用两种原生 rounding policy 证明精度断言，不替换金额算法。
- [x] 扩展现有类级 setup：先替换 frappe.db 属性后才 patch fake 方法；共享异常助手及请求 response/message_log 自动 cleanup；明确不存在的 finance assignment，不以 truthy Mock 冒充已安装模块。ordinary GL fixture 默认空 dimensions，专项保留真实维度和四列比较。
- [x] 真实 native child 对象语义继续使用原生 Document/BaseDocument，仅替换 controller/metadata 查找依赖；不改成 dict 后冒称覆盖原生子行。可选 China Finance 仅为测试作用域的 sys.modules collaborator，生产检查保持原样。
- [x] 保留来源 CAS、当前 ACL、重放篡改、retry 丢弃 artifacts、rollback 原错误、installer 无写入及 GL/auto-PI 覆盖断言。扩展既有 retry 案例，确认失败尝试写入的临时 response/message 不传入下一次尝试，不复制平行事务测试。
- [x] 四个相关模块与 reversal_scope 专项 GREEN 后，运行 workflow 的完整 `FRAPPE_STREAM_LOGGING=1 ./env/bin/python -m pytest -q "$GITHUB_WORKSPACE/deeplinkerp_branding/tests"`（不初始化）；清洁 optional-app 环境单独证明。随后 initialized/native 完整回归、语法/差异检查、规格/质量复审。日志基线子集只用于定位，不抵扣任何失败；GitHub 实际 CI 仍须最终候选通过。

**1B2-CI 限定验收（2026-10-09）：** 冻结 `7dbea995dd58f2cd4c48bccc31dff4df9bc13aa4` 仅五个测试文件 +111/-35，新增一个 23 行共用夹具助手、修改四文件、无删除；原有独立方法 28/36/14/5 共83未增加，保留原断言并加强既有 retry 的请求状态恢复。生产源码和原 Native QA 与已验收 `292c2503` 字节相同。正式独立规格通过后，新独立质量审查通过，无剩余 Critical/Important/可行动 Minor。

主线程对同一冻结实际串行独立执行，均记录真实 exit0：无站点 literal workflow（未关闭默认 cacheprovider）`/tmp/dlp-b2-root-7dbe-sitefree.log` **693/517/46.14s**；阻止 Finance/MES 根及子模块实际导入的 optional 环境 `...-optional.log` **693/517/46.39s**；精确 site/db/host 的 initialized FULL `...-initialized.log` **693/517/48.91s**；原 native 脚本 `...-native.log` **96 methods/225 subtests/115.756s**；Node **479、0 fail/skip/366.050458ms**；17文件编译、diff和源码一致性检查通过。optional及initialized进程结束时八个请求协作对象恢复；独立 setup/method/subtest 故障证明恢复八对象与可选 leaf，实际 native ValidationError/PermissionError 类及消息准确。不是把主动注入的 cleanup 故障计为业务失败。

主线程 readonly before/after proof 的44类计数、User Permission3、六类真实列/完整索引/空指针、十二控制器MRO和scheduler事实逐字段 diff为零。没有MR第七指针，IR/RIV/SLE仍0；frappe.in_test=False、enable_scheduler0、inactive=True。QA/probe 全部退出，仅原 gunicorn90965/90993；Finance `3956eeb...`、MES `73cd5eb...`、native SQL `4ac73f...` 未变，工作树/index clean。交接摘要 `/tmp/dlp-b2-ci-handoff.md` SHA256 `a55b8061b43522cd305c94846983eeb2f0b912e6066c8c3c83a4f15ce03e9058`。据源码、两正式审查和 fresh 执行证据接受有限 CI 夹具步骤，允许进入C1；完整候选的GitHubCI、worker、异步取消、合并业务、界面/browser及Vultr部署均未完成，发布仍HOLD。

### Task 1C：原生 worker 的隔离适配和启用门禁

**Files:** `services/purchase_repost_boundary.py`、`hooks.py`、上述单元/原生测试。扩展原生 RIV controller，不改原生文件。

按顺序拆成可独立审查的窄步骤，不并行写入：**1C1** 核实固定 installed 源及 MES 既有 producer/executor 调用覆盖，必要 IR native-intent 的同事务登记、保护及原队列恢复；**1C2** 原生 RIV captured/scheduled executor、generation/终态/retention 的 shared lease 适配；**1C3** 真实 worker/RQ、跨 commit/断线/并发、恢复及全进程能力和发布 drain 门禁。每步先规格再质量审查，局部通过不开放 D；不能以设计候选或静态检查代替三步真实验收。

C1执行前新增固定源核查（仅设计证据、未实施）：原MES producer在HTTP请求登记 `request.after_response`，原Frappe异常会rollback但该队列仍可能由ClosingIterator执行；因此必须在登记回调前、MR同事务登记intent，回调冻结真实身份，并在派发前读取已提交intent；rollback后的残留回调不得生成幽灵同步。原IR status/service为可空字符串，CI collation下 `status <> 'Completed'` 可能把未知大小写／尾空格值排除；真实索引与EXPLAIN需同时证明严格终态语义和有界读取，不能把未经证明的request_id新语义或全表JSON扫描当既定方案。原get_bin已有缓存/普通RR读及并发unique回退，MES在等待锁后汇总也可能沿用旧RR视图；必须沿真实调用点复用原数学并证明current-read，不只检查新指针。上述均纳入C1原有契约及真实RED，不另建流程或先开放D。

#### C1 冻结候选与限定验收边界（2026-10-09）

实现者已释放全部源码/index/schema/QA/Redis 所有权，冻结 `b327d5e55359547ce0246c212359a5d40fd431a5`，基线 `3aee71852fb3dd7223228e4aa2caf8621d25577e`。主线程已核对实际 commit、干净工作树、八文件 diff 和源码 SHA；正式 fresh SPEC→QUALITY 和主线程独立运行尚未完成。这是 C1 候选，不是完整采购或发布验收。

- 一个 focused `purchase_native_intent.py` 复用同一物理 Session/fence、原 MES 队列/锁/数量计算和现有 IR/审计保留；不新增库存账、DocType、每 pair 锚记录、MR 第七指针、scanner、调度器或重算执行器。真实 MR parent 事务先登记再注册 callback；rollback 残留 callback 不派发，callback 丢失仍留持久 intent。
- **批准的两层来源身份：** 完整 persisted `as_dict` SHA/modified 保留为登记、执行、ACK/replay 证据；producer 身份只排除原生派生/审计字段：MR `modified/modified_by/per_ordered/per_received/transfer_status`，MRI `modified/modified_by/ordered_qty/received_qty`。原生 `status_map` 的普通展示进度归为 eligible，Stopped/Cancelled 保留为不同的因果事实，未经新 producer 登记的资格变化拒绝，未知状态拒绝；正常停用／取消的新 generation 仍委托原生需求清零逻辑，而非绝对禁止执行。未知字段、请求数量/stock_qty/换算、child/item/warehouse/company/type/docstatus 都保留。真实 PO→PR mapper/submit 形成的 ordered/received 进度不得误判成未登记的业务变更，未登记请求事实改变仍拒绝。
- 每次真实 flagged producer 都有新 UUID，包含完整来源及 scoped old/new pairs；同 MR 恢复仅认冻结的 same-actor group，各 generation 只保存自己的 pair 子集和完整 claim 身份。旧 callback 不吸收新 generation；mixed-actor 拒绝，不猜 Administrator 或“最新用户”。
- SERVICE 为 `DeepLinkERP native MES Bin intent`，仅实际 fixed-claim current Bin/nonstock 核对与规范 Completed/ACK 同物理 commit 才确认。入队返回、MES Task Success、RQ finished、空返回或普通 flag 都不是 ACK；新 Job 用真实 Queue.enqueue_call meta/DefaultSerializer，旧 Queued/Started payload 不修改。
- 单个 virtual tinyint `custom_purchase_native_intent_active` 与完整 `(integration_request_service, active, name)` 索引只是有界 selector；BINARY 精确 SERVICE+Completed+ACK 才为 inactive，其余 NULL/未知/大小写/尾空格仍 active。CI service、active=1、FORCE INDEX、ORDER BY name、LIMIT 5001、FOR UPDATE 和零集合均在 fence 下；实际 data+output 长度先于正文读取，保留 5000 records/2500 pair/4 MiB 单条/16 MiB 总量。ACK output 全批预算在首笔 ACK 写入前核对，超限整体回滚 Bin/ACK，不截断。
- 原 MES producer/lock generator/sync/release 采用保留 Function identity 的适配，实际磁盘和 loaded code/globals/defaults/closure/固定对象及依赖一并核查；真实原生 GET_LOCK 每次成功获得 Session/epoch token，旧 finally callback 不能释放后来同名锁。实际 mysqlclient bytes 锁名按已验证 ASCII bytes 等价处理，native 大写异名不 casefold。原 get_bin/unique fallback 和需求聚合在持锁时 current locking read，snapshot=1/RR 不改；旧 RR 冲突 1020 整体回滚后只能用新事务恢复。
- IR native 文档写入/命名/状态/rename/delete 与 routine retention 按持久+proposed 身份保护；creation-only LogSettings IR compaction 在第一笔 DDL/commit 前拒绝。普通其他 SERVICE/doctype 委托原生。不声称任意 raw SQL 或未知 hook-skipping 路径已保护。

实现者最终运行证据：site-free/optional-absence/initialized 各 **693 methods/517 subtests/exit0**，native **137 methods/370 subtests/316.225s/exit0**，Node **479 passed/0 failed/0 skipped**，19 文件 compile、diff 和夹具异常清理检查 exit0；这是实现者结果，尚未由主线程重新执行。主线程只读核对两份 before/after 日志 byte-identical：44 主计数、六空指针、12 MRO 与 scheduler 未变；辅助 DefaultValue229/DocShare137/HasRole869/UserPermission3/ErrorLog296/MES0/0 的完整行摘要一致；仅原 gunicorn90965/90993。helper SHA `485ad67b642ca384929970f2824f85ca9f508ed293d0c3e86a81e95f4e1e59b1`，native harness SHA `9c5fe18734c582c5645aa973994cfb7a81046d77adfc99b1abfb4b486c9abd47`；交接 `/tmp/dlp-c1-freeze-handoff.md`，日志及八源码 SHA manifest 同目录保留。

原生 RED、夹具失败与最终 pass 分开保留：真实 PO 派生进度、RQ meta、bytes SERVICE/锁、output budget/callable 失败不得改称首次 green。首次完整 native **137/365/exit1** 唯一失败是 MyISAM Error Log 的精确 own artifact 清理，不是事务 rollback 能恢复 MyISAM；后续同一测试仅补 own-ref 记名，未改 Finance/logger。无 pre-C1 DocShare 基线，八条有直接归属证据的 fixture share 经批准清理，四条仅时间关联的候选保留在137行，不声称已恢复 pre-C1 全量。

变更为八文件 **+2618/-7，净+2611**：新 helper1007行；installer +59/-0、operation +48/-2、boundary +68/-2、三 unit fixture 共 +9/-2，原生脚本 +1427/-1。无删除文件、原生/Finance/UI 改动或复制队列/数学；native96/225→137/370，新增41方法与145参数展开，不把参数当独立业务流程。兼容退出仍以原生提供等价持久身份、锁/当前读和真实调用迁移为条件，不虚构日期。

**继续 HOLD：** C3 真 worker/fork/recursive retry 的有效 actor 尚未证明；mixed-actor group、超 output 预算 group 的有界批处理、生产11.8.6 matched-engine DDL 与未知 hook-skipping 路径尚未接受。5000 是 selector 上限，不保证5000条同 MR group 的 claim 重复输出都能容纳16 MiB。C2/C3/D/E/合并/来源/UI/browser/GitHub CI/Vultr 尚未验收，不因本候选允许实际异步取消。

**C1 fresh SPEC 不通过（同日，尚未进入 QUALITY）：** 主线程独立核对实际源码后，将两项 Important 交回同一 writer 做真实 RED→GREEN：① `protected()` 对 name 使用 Python 精确 startswith，但 native name/retention 为 CI namespace；新建或 rename 普通 SERVICE 到大小写/重音等价的预留前缀可被准入，既有 canonical SERVICE 记录仍受 stored guard 保护，不能把该缺口说成已证实覆盖原审计。② late-flag gate 只在 document boundary，普通 MR insert 已持有非 fence 租约后，直接 `update_requested_qty()` 会走固定 MES mixin→register，绕过 submit/save gate 再取 fence；必须把同一出版顺序不变量放到 producer 登记前，不中途释放锁或重排事务。现有绿色日志没有这两条真实场景，保持待修，不启用 C2/C3/D 或部署。active-read 的 data+output 预算与终态 ACK output 预算的区别已明确，不增加未经批准的 persisted terminal-group 预算或 enqueue 前来源校验要求。

两项整改冻结为 `59df601cabc91cffd93b3f8e9c64206e11c364c8`，同一 namespace comparator 复用 native CI equality/prefix，同一 publication-order gate 同时供 document 与 register 使用；四文件 +92/-26、净66，不增加协议或兼容别名。真实前缀 RED44参数、late producer RED2路径和首次 fixture 错误分别留档；实现者最终 unit 三环境693/517、native137/417、Node479、19文件compile与夹具异常恢复通过，主线程已核对来源／实际日志但**尚未独立运行**。C1整体基线→整改为八文件 +2684/-7，native独立方法仍137，370→417仅现有两个矩阵参数展开。

整改后的 fresh SPEC **PASS**；fresh QUALITY **WITH FIXES**，无 Critical，但发现一 Important：installer 对 `Key_name`／生成列 `COLUMN_NAME` 使用 Python 精确身份，漏掉实际 native 大小写等价元数据，可能在最终拒绝之前已执行第一笔 ADD COLUMN。另有一 Minor：ordinary release 先 `any()` 消耗 untracked generator，再传给原生 for-loop导致不释放；实际 frozen callback tuple 安全。主线程只读核对固定 mysqlclient.has_index/add_index 与 release helper 确认因果；两项仍是源码发现，不声称线上已发生或已跑实际 DDL。重新交同一 sole writer 做限定 RED→GREEN，复用已有元数据冲突和原生锁矩阵，所有冲突应在第一笔 DDL 前拒绝，不改写既有元数据。整改、复审和主线程独立 QA 完成前不接受 C1、不进入 C2/C3/D 或部署。

**C1 正式限定验收（2026-10-09）：** 上述 QUALITY 两项经真实 RED→GREEN 后冻结 `ef088833470edb85b5407a8da04e45251d0d3a2d`。同一 installer 使用服务端过滤的列／索引元数据并核对完整定义和实际物理列名，冲突在 DDL 前拒绝；兼容大小写别名幂等，不扩大为 native `has_column` 的全面兼容声明。同一 release adapter 只物化一次 iterable，校验及原生委托复用该 tuple，原名称、顺序和 acquisition token 不变。六个元数据与六个 iterable 参数复用既有矩阵，无新增平行测试／协议。真实 RED 七项失败保留，第一笔业务 IR DDL 被拦截而未执行；GREEN 四方法成功。随后 fresh 独立 SPEC→QUALITY 均 **PASS**，无剩余 Critical／Important／可行动 Minor。

主线程对同一冻结独立串行执行，实际 exit0：`/tmp/dlp-c1-root-ef088-sitefree.log` **693/517/46.93s**、`...-optional.log` **693/517/47.60s**、`...-initialized.log` **693/517/50.35s**；`...-native.log` **137 methods/429 subtests/320.600s**，SHA256 `b83b6efc6716bd751f51108c9ef5475bc8b8cd766fb7897d6df5fc8ee265f640`；Node **479 pass/0 fail/0 skip/364.111208ms**，19文件编译和真实夹具 setup/method/subtest 故障 cleanup 通过。原生脚本保持顶层 `frappe.in_test=False`；optional/initialized 八个请求协作对象恢复，实际 native 异常类及消息保持。实现者日志与主线程复验分别保留，不冒称首次 GREEN 或 GitHub CI 已通过。

主线程 `...-proof-{before,after}.log` 的44类计数、User Permission3、六列／完整索引／空指针、十二MRO、scheduler事实 byte-identical；`...-extra-{before,after}.log` 的辅助完整行摘要、IR schema/index、native源SHA与本站MR RQ keys也 byte-identical。三份 proof/source diff 和 compile/diff/index-check 日志均空且 exit0，仅原 gunicorn90965/90993，没有 worker/scheduler/QA/probe 遗留。本窗口无人工清理；既有四条归属不明 DocShare 继续保留，不声称恢复 pre-C1 全量数据。测试前后八源码 SHA 相同，root DOC 在业务冻结范围外。

实际基线 `3aee7185`→`ef088833` 为八文件 **+2792/-7，净+2785**：手写业务 **+1196/-4**，测试 **+1596/-3**；新 helper1010行，其余复用既有 installer/operation/boundary/测试。无删除文件、原生文件／Finance／UI改动、第二库存账／队列／计算器。native96/225→137/429，增加41独立方法、204参数检查；unit693/517不变。最后一次整改仅三文件 **+118/-10**，不能把逐次替换的 numstat 相加冒充整体新增。旧原生调用者仍使用原 Function identity 和原数学／队列；只有原生提供等价持久身份、物理锁／当前读和真实调用迁移验证后才退出适配，不虚构截止日期。

据上述源码、两阶段审查及主线程 fresh 执行接受**有限 C1**，允许进入下面单 voucher 的 C2A；不是接受实际异步取消。C3 worker/actor/drain、mixed-actor恢复、预算超限批处理、生产 MariaDB11.8.6同引擎 DDL、未知 hook-skipping、D/E、合并／来源／UI/browser／GitHub CI／联合 Vultr 发布仍 HOLD，历史数据不处理。

只读核查基线为 native Frappe/ERPNext 16.23.0；主线程已独立核对文件 SHA256：RIV `c4449547d07c76fd316a5b2185d4c9b60bd42e8747767fe28aea28cbc2ceafe1`，background_jobs `7db969deeb19e4a49924c2a59bcdc15e470a3d24d718845ea790fffd94046f45`，ScheduledJobType `80fbb163946521e1413d4ffa6fc8b777d003ee822ba420b4af6b84a47e4875ac`。这些是本地设计核查证据，不代表已跑 worker 并发测试或线上已对齐；发布候选必须重新验证实际原生版本及能力。

- [ ] 先写直接并行 RQ 与 Scheduled Job 两条真实入口的失败测试。Frappe `execute_job` 在 before_job 前已解析直接 callable；before_job 必须为该 captured 原生 executor 取得 lease。ScheduledJobType 在调用自身 method 时才解析函数，before_job 安装一次 process-local `execute_reposting_entry` 包装器，为原生循环逐项取锁。包装器仅调用保存的原函数，不改调度策略、时间窗或算法。
- [ ] `functools.wraps` 保留原生 module/qualname 和 RQ pickle 路径；断言原生 job_name、native started-job 查询和并行 enqueue 路径不变。before_job 在原生 try/finally 外，任何失败自行清理；after_job 释放实际外层提交后的 lease。不得新增直接 enqueue executor 的应用队列。
- [ ] 信任证据来自实际 RQ current job、原生 execute_job func_name、站点、原始 method、persisted Scheduled Job Type 及真实任务 ID；请求参数/flags/job_name 单独不构成证据。当前锁定读取确认 generation/status，再调用 native；终态任务返回，不让 REPEATABLE READ 的旧快照再次执行已完成任务。
- [ ] 用原生 RIV class extension 覆盖 `restart_reposting`（内部 db_update）、`repost_now`、discard/cancel、删除及 `clear_old_logs`。bulk_restart 继续调用原生逐项方法，同一 guard；原生日志清理走 raw delete，必须保留 pending 操作依赖任务，不以 on_trash 代替。完成证据存 IR 后可按原生策略清理无依赖任务。
- [ ] 本操作完成后永久禁止重新启动其已登记的 root/child generation；新业务创建新任务不受该终态保护影响。测试直接调用 Completed root 的 document method、mixed bulk_restart、当前权限被撤销和 old cached scheduler 候选，不只检查前端隐藏的按钮。
- [ ] 测试控制 native repost 内 commit、去重后外层 commit、第二个 cached worker 和最终核对并发：完成状态提交后旧任务不再改 SLE/Bin/GL。模拟断开连接必须实际失败；未知驱动/原生能力关闭 async，不能仅设置未验证的 auto_reconnect 属性。
- [ ] 只读 C 预审并由主线程对照原生源码确认：RIV 内部 rollback418 后仍写 error/status420–457 并 finally commit459–460；execute_reposting_entry 随后 deduplicate674–676，Scheduled execute 和 Frappe execute_job 再外层提交。因此 active lease 必须覆盖这些后续写入，不能以逐项 wrapper 返回或内部 rollback 当退出。根 Completed、原生去重 Skipped、RQ finished/Scheduled Complete 均不替代最终账簿及完整 child coverage。另须核查实际 installed RQ/serializer/virtual RQ Job、retention dispatcher/delete_doc/document-method RPC、RIV defaults/注册 hooks，未给出的原生证据不靠猜测补齐；预审不是 worker 或 C 验收。
- [ ] 固定源的 repost 在生产态吞异常并提交 Failed/In Progress 后正常返回，executor 仍无条件调用 dedup；后者能 raw 写同 pair 更晚任务或同 voucher GL child 为 Skipped。真实失败注入必须覆盖这一顺序，未证明成功覆盖不能据 Skipped 完成或解锁，native dedup 的实际目标身份也在 shared-boundary 保护中。GL child factory 逐条吞 submit 异常且不回写初始去重 map，不能假设一 voucher 一个 child。另核对 Log Settings.clear_log_table 的 creation-only DDL 路径，同时保护 IR 和仍被依赖 RIV；class clear_old_logs/on_trash 不单独证明 retention 完整。
- [ ] 固定 File/controller 与 file_manager 源确认 RIV restart/clear_attachment 会在数据库提交前直接删除本地 blob/thumbnail；原生删除路径没有登记原内容回滚。混合批次须在第一笔状态/文件动作前完整预检，未知 physical-delete 能力不能被数据库 rollback 冒称恢复；对 owned generation 的保护、原生文件清理和失败边界做真实隔离故障测试，复用原生 File 能力，不复制文件或库存算法，不改历史附件。文档 RPC 的整 doc JSON 只有原生 read/latest 检查，不能把 incoming RIV pair/company/status 当持久身份或当前 write 权限证明。
- [ ] C2 HOST 预审由主线程对照固定源码确认：stock_ledger.create_json_gz_file 对已有本地 gzip 使用 raw open("wb")，也不具备数据库回滚恢复。可信 owned 上下文可优先验证原 helper 的 file_name=None 新文件分支，保留旧 checkpoint 并随原生 chunk 提交精确 File/generation cleanup receipt，再由同一 IR reconciliation 复用原 File.delete 重试；不能只靠 after_commit 回调或复制压缩／删除算法。此为待实测候选，必须覆盖共享 hash/thumbnail、新 File 回滚、callback 丢失及物理删除后 ACK 前崩溃；未知 storage 能力保持 HOLD。RPC 精度说明：dt/dn 为 READ，docsJSON 加 latest，submitted→submitted 还检查 SUBMIT；这些均不替代持久 current facts/current WRITE。
- [ ] 已存在的 MES deferred Bin writer 也须隔离，不改 MES 原队列、计算或库存体系。固定 host 副本 `mes_material_request.py` SHA `73cd5eb8d391b53383fd6512b8665bf32bf4604754aa2c43f9d7ffd3d87f255a` 全文件预审发现：RQ 在 before_job 前捕获 sync callable；原 sync 晚绑定 `lock_mes_material_request_bins` 可作为待验证的最窄共同写入 wrapper 候选。逐项解析真实将写入 pairs 的持久 Warehouse 公司（旧 payload、MR 公司变化/缺失均不能只信当前 MR），所有 pending 检查早于第一次 get_bin/写入；核查所有真实调用及 lock-helper alias，不凭模块替换宣布覆盖。原汇总 SELECT 在等待后仍可能使用 RR 旧快照，须真实两连接证明最新计算时序，不能在已有写入后随意 ping/rollback/commit 刷新。
- [ ] MES 阻挡后的恢复是独立验收点：原 Redis 失败 fallback 捕获 sync 异常、可能没有 rollback；MES task Success 不证明 Bin 已同步，原 background_jobs 仅有限次短间隔重试。须复用并验证既有持久操作/原队列恢复机制，使长时间 pending 解除后真实旧 pairs 的 demand 更新不会永久丢失；不新建平行队列或伪称“拒绝写入”已经保证最终一致。没有真实持久重试、fallback 清理和恢复证据则不能启用 D；保留正常无 pending MES 行为，未知能力保持明确禁用。
- [ ] 前述只在取得 lease 后往 reversal IR progress 追加 marker 的候选不足以解决 GET_LOCK 冲突、物理失败和 callback 前崩溃；没有权威 pointer 时不能猜操作归属。必要的新 durable-intent 候选仅复用 Integration Request 元数据及既定 reconciliation scan：在原 `enqueue_mes_material_request_bin_sync` 上游、parent MR **同事务**保存原生 method/job ID/user/MR/exact old pairs 身份，再由原 enqueue_job/short queue/job ID/dedup 承担正常调度，恢复必须调用保存的原 helper/原队列且明确新增恢复语义。仅在 after_commit enqueue_job 后建记录仍有 parent commit→callback 丢失窗口；不能用 side connection 或任意晚 commit 修补。审计记录不是第二套库存算法/执行队列。这个候选仍须证明真实捕获 callable、imported alias、direct/internal caller、回调新事务/失败回滚、权限、旧 pairs 与并发 generation；旧 queued 任务只能沿可恢复 drain/版本换代处理，不历史回填或 purge。不能证明完整 producer/executor 覆盖则继续关闭 D，不将设计写成已实现能力。
- [ ] C1 native-intent 不使用采购 Completed 回执来确认 Bin；现无持久恢复 scanner，D 的统一 reconciliation 必须明确增加独立 SERVICE/type 分支，涵盖没有 reversal 归属的 producer intent。相同 MR/job ID、甚至相同 pairs 的后续数量变化仍是新 generation；callback 晚读 MR.name、dedup 不合并 kwargs、native retry 未传 user 均须用实际 RQ payload/actor 证明精确认领。enqueue 返回、task Success、RQ finished 不作 ack；只认固定 claim 集合、真实 current demand 及 Bin 同事务 durable 提交，不顺带确认后来 generation。
- [ ] 优先复用 IR 现有列的独立 prospective native-intent SERVICE，以实际复合索引、current-read、有界未完成集合和 shared publication fence 定位冻结 old/new pairs，不默认增加每 pair 锚记录或第七类指针。沿既有预算，记录上限 5,000、pair 联合上限 2,500；单 manifest 上限 4 MiB、整次 active-set 读取上限 16 MiB，先读取实际字节长度后再加载正文，超限或未知/空状态拒绝，不截断。Failed 仍未完成，只有真实 ACK 提交后的规范 Completed 可排除；记录列/索引/charset/collation/键长和零集合时序须真实证明。D 在取消及发布指针前遇到相交的未完成 intent 就拒绝并提示先完成原生同步，不先受理再相互等待；登记/ACK/发布都持有同一 fence 到物理提交。这是待验收的最窄方案，不称当前已有完整 producer 覆盖。
- [ ] RQ 原生 Queue.enqueue_call 有 meta，可作为新 Job 的固定 generation manifest 候选，但 Frappe.enqueue 没暴露该参数，不能把 meta 当业务 kwargs 塞入或给旧 queued/started Job 后补/合并身份。只在被证明的原 enqueue 调用边界复用此能力，并验证真实 serializer、dedup、同步 fallback、captured callable 和 actor；没有可信 dispatch/认领证据则 intent 保持未完成，D 不开放。
- [ ] 原 MES GET_LOCK 也须纳入同一物理 Session/epoch 的成功取得与释放兜底，保留原锁协调而不只管理新锁。原 after_commit/after_rollback release 会被 callback reset 或更早异常遗失；真实测试其部分成功、保存点、完整事务失败、迟来的旧 epoch callback、新 epoch 再取同名锁及 KILL/close，不能让旧回调释放新事务的锁。仍复用原数量算法，不复制 inward/outward/planned 计算。
- [ ] 发布启用前必须 drain 旧 worker、重启所有参与 web/queue/scheduler、核对同一候选资源和 hooks/controller 能力。这里的 drain 是停止旧进程接新任务、等待在途任务并可恢复地换代，**不是 purge 队列、删除未执行业务任务或清理历史 RIV**。旧代码已经运行的任务无法靠新钩子追溯隔离；未完成这一步保持 strict 取消限制。QA 也必须重启并测试实际 worker，不用内存 mock 当作部署门禁通过。
- [ ] 原生 ready-for-migration 的 any_job_pending 只看队列 ID 和 started registry，并使用会触发 registry cleanup 的默认查询；不涵盖 intermediate、deferred/scheduled/created/stopped、回调及全部实际进程，不作为唯一 drain 证据。沿已核查 RQ 2.6.1 的只读原始队列/registry/execution/worker 身份核对完整范围，保留 orphan/缺 hash 的不确定性；不调用 purge、cleanup、重排队来制造空队列，也不将 pickle job_name 或 worker 的 RQ package version 当应用候选 SHA。
- [ ] C3 HOST 预审与主线程固定源码复核：原 RQ prepare_execution 创建 Worker.execution，fork 继承该对象但只导出 RQ_WORKER_ID/RQ_JOB_ID，不存在可直接相信的 RQ_EXECUTION_ID。实际 pinned perform_job 与 Frappe execute_job frame 的有界只读 witness 可作为候选，但不改运行中的 frame locals、不取注册表“最新一条”冒充实际执行。before_job 在 native try 外，前置 after_job 抛错可跳过 destroy；租约必须有原 execute_job 的完整外层 owner 或实证等价 fork 生命周期清理，单加 after_job 不够。这些尚未实现或跑 fresh worker，不作为 C3 通过证据。
- [ ] 保存 native 版本及相关入口的能力签名；升级变更在集成测试发现并失败关闭。冻结、专项/原生回归、规格审查、质量审查通过后才进入 1D。

#### C2/C3 固定原生审计的后续实现精度（仍未实现）

- C2 不只扩展 RIV class：`process_sle` 的真实 SLE/related 输出与 FIFO queue、stock checkpoint commit **早于** progress 写入、GL commit **早于** gl index 更新。复用同一 Session 的物理 COMMIT seam，在原 before_commit callbacks 后、物理 commit 前写同事务 chunk receipt；rollback 清除本 epoch 证据，未知 commit 响应须查持久结果。捕获真实 future SLE ID/最早 anchor 与完整 expected GL 计划，包括 unchanged/empty 覆盖，不用构造函数返回或 RIV Completed 代替。
- 复用现有 ScopeCollector 的 SLE/anchors，不复制闭包。可信 lease 覆盖 native RIV rollback→error/status→finally commit、deduplicate 和 Frappe outer commit。普通原生 stock input、PR/PI 的 valuation/SVD 路径需核对实际 projection/multiset 与锁定当前事实；原生 class wrapper 单独不能覆盖 captured aliases 与内部 chunks。
- checkpoint 沿原 `create_json_gz_file(file_name=None)` 候选，保留旧文件直到新 pointer+receipt commit；复用原 File 删除，实际 File/generation 而非“首个 attachment”是身份。raw overwrite/预提交物理删除不可冒称 DB 可回滚；共享 blob/hash/thumbnail、callback 丢失、删除后 ACK 前 crash 和 storage byte 上限要真实验收。
- C3 沿实际 RQ `prepare_execution→fork→perform_job→Job.perform→execute_job` 的 execution/进程/site/原 method/serializer witness，不把环境 jobID、latest registry 或本地 flag 当实际身份。native recursive retry 丢 user，必须在真实 worker 内保留原 actor 与 C1 meta；不修改运行 frame locals。before_job/after_job 在 native try 边界外可失败，`os._exit` 可绕过 finally；须证明物理连接已消失、peer lease 已释放。Simple/Spawn/未知 worker 不自动视为支持。

**C2A 的最小后续切片（C1 已限定接受，本切片未实施）：** 扩展同一 Session COMMIT seam 的 epoch receipt substrate，并用一个新合成、owned、Transaction GL-only RIV 跑真实控制器；限单 voucher、无旧 attachment/checkpoint、无 recreate/rerate，不设置 **reversal IR／应用最终 Completed/ACK**、不清指针。保留原生 RIV 自身 Completed/finally commit，但它不是冲销完成证据。IR 同一受理记录保留 immutable task/generation/actor/site/db/scope/native参数与 bounded partial receipt，区分 control-only commit 和真实 GL 效果；不调用会覆盖 data/output 并标 Completed 的同步 `complete_audit`，也不进入会覆盖 acceptance data 的普通 `operation.run/bind_operation/finish_native_audit` context。仅 private prospective ownership，逐项锁定实际 IR/RIV 身份，复用 publication fence 与来源／pair leases；普通 RPC/flags/pointer/docstatus 单独不能获得 authority，C3/D 不开放。callback reset、raw/nested commit、savepoint/full rollback、receipt-write failure、commit 响应未知及 GL commit→progress 更新失败先有实际 RED。stock constructor 即使少于2000行也会写 checkpoint，不能借“小批 stock”假装没有物理文件问题。

文件边界：物理 epoch／COMMIT substrate 仍修改 `purchase_repost_boundary.py`；允许新增一个 focused `purchase_native_repost.py` 专门放原生 RIV／GL 输入与 partial receipt 适配，复用现有 IR、encode、ledger reader 和同一 Function auditor，不塞入 MES intent 职责或建立第二受理／队列／重算流程。扩展既有 unit/native harness，不复制 runner；该 helper 的实际范围／行数仍在冻结和两阶段审查中核对，增长超出本切片则暂停报告。

**C2A1 限定验收（2026-10-09）：** 冻结 `40b81e0fe7a2c89dc4e7d450c606984f4fb1cfb5`，只扩展同一 Session 的 dormant private epoch receipt 协议。prepare 在原 callback 后、物理 COMMIT 前；有界 detached candidate 与物理身份、原 owner 关闭后才允许的 exact-byte 不确定结果查询，以及已提交／回滚／后续 callback epoch 分开处理。普通入口统一在现有 authority 首部禁止 promote/invalidate 的 SQL 和租约重入；没有新受理、队列、业务 owner、native GL/RIV adapter、应用 Completed/ACK 或解除指针。三项正式审查缺口均在既有矩阵实际 RED→GREEN，最终 fresh SPEC→QUALITY 均 PASS；不把旧 SHA 的全套通过算作最终版本证据。

主线程对最终 SHA 独立串行实际 exit0：`/tmp/dlp-c2a1-root-40b8-sitefree.log` **710/561 subtests/45.93s**、`...-optional.log` **710/561/48.56s**、`...-initialized.log` **710/561/50.18s**；`...-native.log` **150 methods/456 subtests/328.353s**，顶层 `frappe.in_test=False`，结束 SESSION_DESTROYED；Node **479 pass/0 fail/0 skip/459.368709ms**；19 文件编译、夹具故障清理、源码和 diff/index 核对通过。复用既有 runner，Docker endpoint 实际为本机 desktop-linux unix socket，不在 Vultr 测试或构建。七源 before/after SHA、44 类计数、辅助完整行摘要、六空指针/物理元数据、MRO、scheduler、native 源和本站 MR RQ keys 均一致，仅原 gunicorn90965/90993，无 QA/worker/probe 遗留。

测试隔离的明确限制：实现者旧 full 的 107 表摘要中 Warehouse 与旧 baseline 不同，缺旧 raw rows，未猜值恢复。主线程 fresh full 另行采集实际 before/after，确认 12 个原仓库身份一致、所有非 lft/rgt 字段摘要一致；仅 `All Warehouses - QAB.rgt`、`QA Selection - QAB.lft/rgt`、`QA Selection - Y.lft/rgt` 变化。既有 native Warehouse.insert 与 exact new-row raw delete 清理没有恢复原树索引是源码支持的原因；不能声称全部表逐字段恢复或已修复历史 QA baseline。后续只允许在同一 fixture 内捕获、核对并还原该 fixture 自己造成的精确树索引差异，不 rebuild tree 或清理归属不明历史行。此次未做人工恢复或生产操作。

相对 `1df9e837` 三文件：业务 **+119/-4**、测试 **+779/-1**，净 **+893**；无新增/删除文件或生成物。unit693/517→710/561 增加17独立方法、44参数检查；native137/429→150/456增加13协议方法、27参数检查，不冒称真实 GL/RIV 业务场景。没有第二套流程；原 callback/SQL/原生数学及队列兼容继续保留，等原生提供等价 physical receipt 能力且真实调用迁移验收后才退出，不虚构日期。

**C2A2 限定验收（2026-10-09）：** 冻结 `84f12379e9d632d06932923eb80b801026c9d16f`，只扩展同一 `_audited_function` 的 keyword-only frozen getter 路径；原 plain/no-closure predicate 不变。完整实际 `caching.py` 269 行及两个 loaded native wrapper/getter 已取得：缓存源码 SHA `95260b7ea1bda8133e1ac127a4bd90628f688450af4a7020e469bb57600329a5`，HOST 只读副本 `/tmp/dlp-c2a2-native-cache.AUi6ve/caching.py`。独立 namespace/source pin、request_cache 下直接 wrapper code、一个 func cell 与 wrapped 的 exact getter identity 均校验；复用原 auditor 校验 getter code/globals/default types/kwdefaults，不支持任意 closure 或其他缓存装饰器。没有执行 getter、修改 native aliases、增加 helper/runner/installer/owner/Completed/ACK/public capability，也不证明缓存值为 CURRENT。

实际 RED 区分缺 keyword API 的诊断和原 `8b3bf7b` auditor 对两个真实 wrapper 返回 False 的独立语义失败。冻结后 fresh SPEC→QUALITY 均 PASS，无可行动问题；主线程串行独立复验 whole boundary unit **43/107 subtests/0.15s**、既有 private native matrix **1/44/0.034s**、三源 pin/编译/diff/index，通过且无站点初始化；原生 sources/aliases 前后相同，顶层 `frappe.in_test=False`，仅原 gunicorn90965/90993，未生成 pycache。没有重复运行完整710/150套件或声称 GL/RIV 业务通过。三既有文件：业务 **+28/-1**、测试 **+136**；新增1 unit方法/5参数检查，native既有方法新增44参数（2正向、42拒绝），无新文件、删除文件或第二 auditor。原 no-closure 调用继续兼容；原生提供等价受信调用证据且实际调用迁移验收后才移除此固定版本兼容，不虚构日期。源码升级需重新审计 pin，cache freshness/helper contents 尚待业务适配；证据与命令 `/tmp/dlp-c2a2-cache-handoff.md`。

**C2A 后续顺序：** C2A1/C2A2 仅接受以上 substrate/audit prerequisite；先修同一 native fixture 自己造成的 Warehouse 树索引泄漏，再做合并版本 full 回归，不再用失败清理制造新漂移。fixture 必须登记实际新增叶节点身份，旧树坐标增量须由这些实际端点精确解释，旧非树字段/身份一致才可在同一清理事务恢复当前测试开始时的 lft/rgt；commit→after_commit 报错路径沿既有 finally 登记，清理不得接纳未登记身份或猜值恢复历史。随后才实现原计划单 voucher native GL/CURRENT-input/partial receipt；C3、D/E、合并入库/付款、同步、金蝶式 UI/browser、联合 CI/Vultr 均未完成，生产 async 和发布继续 HOLD。

原生 GL 的 per-voucher witness 候选是 `accounts_utils.repost_gle_for_stock_vouchers` 中 `toggle_debit_credit_if_negative` 的**直接调用返回**，早于比较/删除/记账，包含 expected-empty/existing-empty 分支；只适配 compare 或在外层返回观察都漏证据。主线程已只读取得并核对 QA 实际 `general_ledger.py`，HOST/container SHA均为 `c2228231802b3d979043bc91f0819b7d9e884c72c32051659456cbbe32f91b84`；helper365–406签名仅 `gl_map`、无 defaults/closure、原对象原顺序返回，实际金额处理含 base/account/transaction 三对字段。loaded-object/runtime 核查尚未执行；须复用同一 in-place auditor 保留 aliases，核查直接 caller edge 而非任意 ancestor frame，原返回对象/顺序不改，冻结完整有界拷贝及实际 voucher/chunk/precision/existingGL。嵌套 `get_gl_entries`／`process_gl_map` 内 toggle 仍透传；异常、空 input 或 resume index 跳过全部凭证不能冒称 coverage。这个 witness 只是 **pre-posting expected map**：后续 `process_gl_map` 分配成本中心／合并，`save_entries` 还处理差额／维度／提交，不能冒称已与最终 GL 相等。初期保留单 voucher 与 partial 限制，后续多 voucher chunk 在逐项 witness 真正验收后才放开。此段是 HOST 源支持的切片建议，不是 native/QA/规格/质量通过证据。

C2A 输入证据须比较 native 实际 projected multiset／scalar 与同租约当前锁定事实，保留重复与原选择语义；app `current_reads` 仅替换本应用 reader，C1 query adapter 仅覆盖 Bin／MES，均不证明 native GL/SLE/PR/PI／缓存输入已 current。保存实际 native `get_field_precision(GL.debit) or 2`，不代换成币种／展示精度；existingGL 八列 projection 不冒称完整账务证据。真实旧 RR、peer GL/SLE/parent变化、重复投影／缓存过期须先 RED；无法证明的 native 分支保持 HOLD，不通过重跑写入算法造证据。GL-only 仍可原生删除／创建 PLE，须记录实际 PLE footprint 或实证 fixture 无 PLE，不扩大为应付／资金最终验收。

### Task 1D：原子受理、持久阶段与最终核对

**Files:**

- Create: `deeplinkerp_branding/services/purchase_reversal_progress.py`：唯一 IR 上的阶段服务、对账恢复和有限 retry。
- Modify: `purchase_operation.py`、`purchase_consistency.py`、`hooks.py`；复用原有 source/finance/ledger checker 和运行日志。
- Test: `deeplinkerp_branding/tests/test_purchase_reversal_progress.py`、隔离原生测试。

**IR 数据契约：** 接受事实与可变进度分开。下列为真实受理记录形状示例，不是新 DocType：

```json
{"reversal":{"schema":1,"acceptance":{"source":{"doctype":"Purchase Receipt","name":"QA-PR"},"company":"QA Second Company","scope":{"pairs":[],"sources":[],"vouchers":[]},"root_tasks":[],"capabilities":{}},"progress":{"stage":"waiting_inventory","reason_id":null,"dependencies":[],"final_evidence":null}}}
```

实际数组必须由原单和 native 创建上下文填充；示例的空 scope 不可受理。受理事实在 Queued 后不可改写；未授权用户无法修改进度或清除指针。stage 固定为 `waiting_inventory/recalculating/verifying/completed/failed`，仅最终 completed 映射 IR Completed，其余处理中 Queued、失败 Failed。

- [ ] 先写无 RIV 同步取消和真实 stock 取消对照：严格普通操作不退化；只有实际 submitted→cancelled procurement 路径且创建 native RIV 才允许受理。源 docstatus2、同步账务/China cancellation、scope 指针、真实根任务和 Queued IR 同事务。每个接受步骤故障注入整体回滚，不能在事务内跑 repost 执行器。
- [ ] 捕获实际 `on_submit` RIV 对象，包括 Item/Warehouse 无 voucher 字段的根；禁止事后按日期模糊推断。现有 check_native_repost 仅在实际 server acceptance 上下文允许该例外，普通改价/submit、历史 pending 和伪造 bypass 仍失败关闭。
- [ ] 扩展相同操作键 replay：payload/user/current ACL 仍校验，但 accepted 操作返回持久当前 progress，不按受理时未完成的流水 hash 否定合法后台重算，不再次取消。完成之后重放核对最终证据；失去源权限则拒绝读取。
- [ ] 新 readonly progress API：`get_reversal_progress(doctype, name)` 返回 operation_id、stage、fixed message、safe reason_id、can_retry；按真实来源原生 read 权限，不返回原始 data/output。retry 只恢复本操作真实任务，检查当前办理权限；不重新 cancel、重写快照或创建第二条重算。
- [ ] 定期扫描仅本 SERVICE 的本次 accepted 未完成 IR；aftercommit 仅通知对账加速，失败不丢记录。保留 native scheduler/timeslots，根/child 在 Queued 或 In Progress 时只更新阶段；不从应用直接执行/再 enqueue RIV。
- [ ] 递归核对实际 root/ref 链及 frozen expected voucher coverage。Failed/Cancelled/missing 或裸 Skipped 不能完成；如接受替代必须证明 Completed 覆盖和账簿一致。GL 子任务创建吞异常案例即使父任务 Completed 也拒绝。
- [ ] 在相同会话隔离锁下校验所有 scope pair 的 SLE 数量/估值递推、Bin 与 latest SLE、仓库公司；原生 expected GL 计划和实际四列/维度；采购来源量、原生 PLE/AP、China Posting/Cancellation 日期/来源/反向链接与金额。复用 `_compare_gl` 等既有函数，不写第二套库存计算或财务凭证。
- [ ] future GL 与旧中国 Posting 漂移保持 failed 和指针，不修改历史快照。校验/完成/指针清除逐点故障注入，必须整个最终事务回滚；已经提交的原生 chunk 不声称回滚。终态和解除拦截同事务成功后才 Completed。
- [ ] 覆盖响应丢失、重复点击、Redis 丢失、重启、两连接并发、native recoverable/permanent error、遗漏 child、Skipped after failure、审计篡改/retention 和 rollback 日志留存；顶层 `frappe.in_test=False`。
- [ ] 专项/完整/原生/语法回归后冻结，先规格后质量审查；未完成该任务不开放生产 async。

D 的只读完成校验必须由**实际 native input/branch 与 chunk receipt**验证真实输出，不能仅核对一套内部自洽但过时的数字。future frontier 保留实际 SLE IDs/anchors，不按全局日期扩到所有 footprint pair；reconciliation/serial/batch/negative stock 按真实分支，不套通用 qty×rate 或 queue sum。FIFO/LIFO 顺序也是未来估值输入，native GL expected 四列/维度/重复行须完整比较。缺 receipt/input/branch/future coverage 保持 HOLD；readonly verifier 不调用写入 executor。受理前遇 C1 active intersection 就拒绝，不先取消再互等；最终当前来源/Bin 指针清除和 Completed 同事务，RIV generation 终态关系永久保留，失败不重新 cancel 或开第二队列。

### Task 1E：统一进度显示，复用列表、抽屉和标准表单

**Files:** 既有 `purchase_payment_service.py`、`purchase_document_actions.py`、`public/js/purchase_payments.js`、`purchase_payment_form.js`、`compact_list.js`，以及它们的现有 tests。

- [ ] 先扩展现有 projection/chain 测试，加入唯一 progress 输出和操作禁止原因；前端 tests 覆盖五阶段与 docstatus2 并列、受理消息不报完成、取消窗口无写入、失败刷新不默认完成。
- [ ] 复用统一 drawer/form/list 获取进度；未完成禁用实际入库/应付/付款/修改/取消后续按钮，不建立新取消入口。Backend 同一 scope guard 保持权威。native 当前权限被撤销时立即去掉操作能力。
- [ ] 收到受理结果显示“取消已受理，库存重算未完成”；只在 server completed 刷新后显示“冲销完成”。轮询失败保留最后可信阶段和重试提示；不以 timeout、docstatus2 或 HTTP200 推断成功。
- [ ] 真实本地 browser 逐条验证 native form、采购 list、receipt list 和 drawer 的阶段/拦截/自动刷新，无提交的 preview/cancel 路径零业务写入；记录所用 QA/asset SHA。运行 `node --test tests/*.test.js`、asset build 及资源副本核对，规格/质量审查。

**整项异步业务本地候选（2026-10-09，取代后续安全微切片）：** 在同一 `purchase_operation` IR 和 `Session.receipt_participant` 上接通受理、原生 common repost adapter、partial receipts、只读完成/失败恢复及现有 form/list/drawer/inventory 行为；不新增 Doctype、库存队列或复制估值算法。实际 native affected 18 tests / 75.770s / exit 0，包含 12 个新增业务方法：真实 future-PR 受理→executor→完成、Transfer→Repack 与 Item/Warehouse roots、stock checkpoint、GL commit-before-index、遗漏 GL child、最终 verifier 失败、当前 ACL/幂等/具体绕过、两连接旧 worker、COMMIT 响应丢失、受理/最终事务故障、库存移动拦截、未来 GL 与旧 China Posting 漂移。另 6 个原有严格/无 RIV/闭包回归通过。日志 `/tmp/dlp-async-native-final.log`；165 边界单元、357 passed/1 原有 skip 查询/库存测试、237 UI tests 均 exit 0，分别见 `/tmp/dlp-async-unit-final.log`、`/tmp/dlp-async-host-final.log`、`/tmp/dlp-async-ui-final.log`。原生真实 `names` keyword 的空 bulk 兼容定向 RED→GREEN 见 `/tmp/dlp-async-bulk-keyword-{red,green}.log`；无任务重置或业务写入。

原生夹具 finally 在 rollback 后重新记名，覆盖 callback/response-loss 隐藏的持久副作用；新 File 按精确身份、实际 native root/新物料、附件行及 checkpoint 内容记录后使用原生删除，保留共享物理文件的既有引用。每个新增场景全 51 类计数恢复，控制项 `[auto_submit_PI, auto_insert_price, update_price]=[0,1,0]`、六指针全 0；最终 runtime/只读 mounts 证据 `/tmp/dlp-async-runtime-final.json`、`/tmp/dlp-async-scheduler-final.json`、`/tmp/dlp-async-mounts-final.json`。Finance/OA 固定只读绑定和四个 native SHA 未变；`frappe.in_test=False`、scheduler disabled、仅原有两个 gunicorn。库存资源版本 `0.0.3`、付款 `0.0.25` 已更新。

限定债务/兼容：旧 File `d7c7005696`、`db14d58d6e`、`0abda2184c` 原样保留，均为 88-byte 空 checkpoint、SHA256 `1640004941e68ac751a4c1e8403695bec559505f3af6b989b7301750b3270327`，缺少来源物料交叉证明，不按时间/文件名清理。MES、未证明制造/委外、serial/batch、特殊 reconciliation 等已有未知路径保持受理前拒绝；普通 PR、Transfer/Repack 已实际适配。保留 native scheduler/同步取消及现有 Finance getter 兼容层，只有原生提供等价持久进度/权限/租约/丢响应保证并迁移真实调用后才退出。最终完成后的 checkpoint 清理若发生独立文件故障，只保留临时文件并记录安全日志，不倒改业务 Completed；自动清理重试未扩展为新队列。等待整体 SPEC → Quality；完整 browser/CI/窄联合 schema/真实 drain/生产部署继续由唯一发布线程串行处理，不据局部回归宣告整个采购项目完成。

**整体 SPEC 五项修正（2026-10-09）：** 复用现有闭包/原生任务边界，实际库存取消前核查 Item、明细与 SLE 的 serial/batch/bundle；无 RIV 的 PO/PE/非成本调整 PI 保持同步。相交 unowned RIV 创建/提交/重启提前拒绝，真实受理 roots/已证实 children 仅用服务私有身份；无关 RIV 可完成，无 future 的独立 submit 在 owned worker 持 fence 时仍可办理。实际 RIV producer 按 fence-first 短期串行化，不因无关 pending 全站拒绝；迟出现未证明 producer 整事务拒绝。纯 final 校验补齐 sources∪vouchers PI 的原生 PLE/AP/balance 与 CURRENT 取消 GL/PLE，损坏只读 Failed+保留拦截；HTTP fresh response 同 key 重放返回当前顶层进度。既有库存实例接进度事件及生命周期轮询，失败保留可信 pending，完成显式刷新选中项，离页丢弃旧响应；库存 JS 缓存版本 `0.0.4`。

本轮仅受影响 native 9 tests / 51.971s（`/tmp/dlp-async-review-native-final.log`），随后 stock-only serial 同步边界 1 / 4.774s（`/tmp/dlp-async-review-serial-synchronous-green.log`）及最终 RIV mutation/checkpoint 2 / 14.415s（`/tmp/dlp-async-review-mutation-green.log`）均 exit 0；复用现有夹具，新增两个独立 native 业务方法（serial/batch 三实际证据路径、金融成功及三损坏参数展开）。71 边界单元与最终 43 scope 单元 exit 0，日志 `/tmp/dlp-async-review-unit.log`、`/tmp/dlp-async-review-scope-final.log`；192 host/page contract 测试（内部执行 Node 页面用例，不是浏览器验收）exit 0，日志 `/tmp/dlp-async-review-ui-final.log`。54 类夹具计数、六指针、配置恢复；原 51 类计数与三条限定旧 File 完整行/内容摘要保持不变，Finance/OA/四 native 哈希未变，见 `/tmp/dlp-async-review-runtime-final.json`、`/tmp/dlp-async-review-runtime-compare.log`、`/tmp/dlp-async-review-mounts-final.json`。QA 运行期 hook 缓存仍是 `0.0.3`，源码为 `0.0.4`；由后续联合发布清缓存及真实 browser 核对，不声称此轮已加载新页面资源。修正后等待同一 SPEC → Quality 复审，不启动联合发布或另轮全矩阵。

**整体 Quality 四项收尾（2026-10-09）：** 同一 checkpoint guard 核查 File 持久旧关联、拟保存关联及 URL alias，并由极小 File mixin 在原生移动/物理删除前调用；owned 原生不可变新 checkpoint 与完成后清理仍可用。进度、列表和库存投影全部使用非锁定读取，执行/retry/generation 仍锁定；实际两连接在 final 持 IR/source 锁时完成三类读取，40 条查询无 `FOR UPDATE`，native 未被误标 Failed。只读 billing final 传持久 context，真实不开票回写 stock PI 退货取消保持 billed amount 24.68 并完成。标准表单清除新草稿旧状态/计时器，异步读取与 save 回调绑定当前单据身份，同时保留原生 `localname` 首次保存映射；付款资源版本 `0.0.26`。

仅受影响 native 三场景 3 / 16.076s，最后 native-owned File alias 兼容自查后 checkpoint 单项 1 / 5.974s，Node form/drawer 34、host 资源契约 13、consistency 单元 28 均 exit 0；日志 `/tmp/dlp-async-quality-native-final.log`、`/tmp/dlp-async-quality-checkpoint-final.log`、`/tmp/dlp-async-quality-form-final.log`、`/tmp/dlp-async-quality-assets-final.log`、`/tmp/dlp-async-quality-unit-final.log`。新增一个独立 native 退货业务方法、两个 Node 身份场景，扩展既有 checkpoint/双连接方法，File 变体为参数展开。独有 131-byte checkpoint 实际物理删除 RED 后仅按已证明 root/来源/物料/原 DB hash 用 native File 写回并沿既有 finally 清理；同一场景 finally 仅恢复当次精确捕获的原字节，未知附件不吞错。最终 54 类计数、六指针 0、controls `[0,1,0]`、scheduler disabled、`frappe.in_test=False`、Finance/OA/四 native 哈希及旧三 File 全行/88-byte/SHA 均恢复不变，证据 `/tmp/dlp-async-quality-runtime-final.json`、`/tmp/dlp-async-quality-runtime-compare.log`、`/tmp/dlp-async-quality-mounts-final.json`。只在隔离验证进程以临时 developer-mode 读取当前原生 hooks；未清全局缓存/restart/build/browser，服务缓存仍为付款 `0.0.25`、库存 `0.0.3`。等待同一 SPEC → Quality 复核，后续联合发布继续 HOLD。

### 后续采购任务与统一发布

- [x] PI 原生 hold/release 本地实现及专项验证：复用 `_native_documents_action`、当前 source 锁、`_procurement_call`、`operation.run` 完成整次 block/unblock/change-release；每个完整动作一条 IR，保留原生 None 返回。纯只读核对仅允许冻结三字段及原生修改时间改变，精确对比完整 PI/来源、GL/SLE/PLE/APLE 和既有 China 凭证/同步问题/现金流指定，不调用金额计算或 Finance 创建/修复。审计快照包含 on_hold/release_date，不记录自由文本 hold_comment；receipt/artifact 回放使用当前 write，已提交 PI 不误要求 submit。procurement 单一付款资格 helper 对齐原生 PE 的 on_hold 最终拒绝，到期仍须显式 unblock；既存 PE 保持可只读查看，准备/确认被当前冻结拦截。混合 hold+业务字段 raw db_set 和提前 commit 均拒绝，原生 draft 动作及 REST allow_on_submit 拒绝保留。此项完成不代表完整候选、正式两阶段复审、browser、CI 或联合发布完成。

  2026-10-09 基线 `9ff6e5867831f5a00f1699f16cc65618e91fc88d` 的同一 QA runner 首次 RED **3 methods / 10 failures / 16.830s**，真实缺口为六个 draft/submitted 动作无统一 audit、postcheck/audit failure 未进入整次回滚、到期冻结仍列为可付款，另含 mixed raw db_set 误通过。`commit=True` 真实 RED **1 / 1 failure / 8.035s** 单独保留。首次 GREEN 2 个 hold 方法通过；第三个因错误要求只读 PE preview 抛错而失败，已按授权业务边界改为 target/batch/draft preparation 与 saved PE confirmation。受影响四方法随后 **4 / 29.610s / exit0**（含原既存合并 PE 场景，`/tmp/dlp-hold-native-green-before-selfreview.log`）；自查改为明确 current-read、禁止 native 嵌套提前 commit、移除重复测试 wrapper 后最终三方法 **3 / 24.903s / exit0**，日志 `/tmp/dlp-hold-native-final.log`。实际 partial SQL、postcheck/audit exception、PI 总额和 PO 开票事实损坏均整次回滚，真实 redacted runtime failure 日志 `/tmp/dlp-hold-runtime-operation-evidence.json`。

  最终命令：`env -u DOCKER_HOST docker --context desktop-linux exec -e PYTHONDONTWRITEBYTECODE=1 -w /home/frappe/frappe-bench/sites dlp-kingdee-purchase-qa-backend-1 /home/frappe/frappe-bench/env/bin/python /workspace/deploy/local/test_purchase_document_actions_qa.py --tests test_native_purchase_invoice_hold_db_set_pending_refuses_entire_block_and_clear_works test_native_purchase_invoice_partial_hold_failure_rolls_back_prior_real_fields test_native_purchase_invoice_due_release_requires_explicit_unblock_for_payment`。单元命令：`env -u DOCKER_HOST docker --context desktop-linux exec -e PYTHONDONTWRITEBYTECODE=1 -e FRAPPE_STREAM_LOGGING=1 -w /workspace dlp-kingdee-purchase-qa-backend-1 /home/frappe/frappe-bench/env/bin/python -m unittest deeplinkerp_branding.tests.test_purchase_consistency deeplinkerp_branding.tests.test_purchase_operation deeplinkerp_branding.tests.test_purchase_document_actions`，**82 / 0.476s / exit0**，`/tmp/dlp-hold-unit-final.log`；首次遗漏既有 stream logging 环境为 **21 errors**（`/logs/purchase_operation.log` 不存在），证据 `/tmp/dlp-hold-unit-environment-failure.log`，未修改业务日志。六个 Python 文件语法及 diff-check exit0，`/tmp/dlp-hold-syntax-final.log`。

  新增一个独立 native 到期冻结业务方法，扩展两个原有 hold 方法；全 runner 独立方法 **180→181**，draft/submitted × 三动作、四个付款入口及两种失败阶段为参数展开，未复制 gate 矩阵。五个手写业务文件 **+101/-16（净85）**，同一测试文件 **+115/-8（净107）**；无新增文件、服务、RPC、schema、生成物或长期兼容分叉，无删除文件。删除被完整 adapter 替代的直接 hold db_set 分支及采购读取的原生到期放行调用；原生 `invoice_is_blocked` 和原始原生动作仍为真实调用，无退出需求。复用检查及只读自查均未发现新增重复流程；正式候选 SPEC→Quality、联合 full suites/browser/CI/Vultr 仍待唯一发布者串行完成。

  复用前轮瞬态 runtime inspector 获取 fresh before/after：`/tmp/dlp-hold-runtime-before.json`、`/tmp/dlp-hold-runtime-final.json`、`/tmp/dlp-hold-runtime-compare.log`、`/tmp/dlp-hold-mounts-{before,final}.json`。**54 类计数、六指针0、controls `[0,1,0]`、scheduler disabled、`frappe.in_test=False`、Finance/OA/四 native 哈希、同一 gunicorn PID1/11、三条未知旧 File 完整行/88-byte/SHA、runtime cached assets 全部不变**；仅本 runner SHA 因测试修改改变。所有夹具沿既有 finally 按精确新增身份清理，未按 pattern/time 清 File。瞬态诊断先因 mount 返回顺序及错误要求 ERROR-level 日志含 INFO success 而失败，后按完整 mount 身份排序和实际失败事件核实；无状态漂移。无生产访问、cache clear、restart、build、browser 或 deploy；旧三 File 等既定债务保持原样。

- [ ] 合并入库继续扩展 `purchase_document_actions` 的原生 mapper、税费兼容和真实 source row，批量整事务；付款继续扩展 `purchase_payment_service` 的真实 PI 去重和同公司/供应商/币种核销。不能由两个新 standalone 业务服务替代已有入口。
- [ ] 同步继续复用 `purchase_source_service` 的审批判定、版本和人工值保护，完整有效来源仅建 PO draft，缺项留同页待完善；读取失败整批不落部分数据。不得生成同步付款或覆盖历史付款。
- [ ] UI 继续复用 compact_list/payments：主表真实订单、待完善独立同页 tab、真实物料明细 rowspan、整单选择、当前页全选、统一布局迁移与集中操作栏；旧组合列默认值只迁移本采购配置，其他模块不变。
- [ ] UI 复用核查已限定实际边界：保留 unified_purchase_service 的过滤→排序→整单分页，待完善按 row_type=oa_request，不把包括已关联真实订单的 source=OA 直接改名；复用 purchase_order_progress 批量 include_items 和原 PO Item.name。TABLE/rowspan 与分页/清选配置扩展 compact_list，不另建列表；精确识别旧七列默认（其版本已是2），保留真实自定义列和密度。复用 payments/actions 抽屉，扩展同服务的真实多来源 mapper/PI 去重；替代后删除旧箭头/组合渲染，保留 crossborder 等真实调用的刷新、抽屉及标准表单兼容契约，迁移和调用验证后才删旧显示。沿用现有测试修改旧呈现断言，保留权限、过期响应、来源人工值及独立业务约束。
- [ ] 完整候选串行吸收唯一发布者较新 Branding 基线，保留 dirty/untracked/server 状态；核对 Finance 固定候选、联合 CI、相关窄 schema 安装、全量回归、真实 browser 采购→入库→应付→付款流程。不是只发布冲销补丁。
- [ ] 交付独立跨模块联动清单、数据一致性校验点、测试用例与实际结果；分类统计新增/修改/删除、重复逻辑、手写业务/测试/文档行数、业务场景/参数展开、兼容真实调用与退出条件及未处理债务。
- [ ] 由既定唯一负责人 drain/部署/清缓存/重启并核查 Vultr SHA 和所有 worker 能力，再在线只读检查真实页面及 preview/cancel。线上真实提交/取消不得作为验收测试。所有影响页面尚未验收时不报告完整完成。
- [ ] 发布脚本现有 narrow metadata scope 尚未包含六类 reversal 指针和 native scheduler 适配，需在最终候选扩展同一审计/窄安装/恢复工具；不能靠全局 migrate 顺便安装。现有 `quiesce_release_workers` 的 compose stop 不单独构成在途任务已 drain 的证明；记录真实 job/进程退出及恢复策略，保留队列和历史 RIV，完成门禁后才启用新异步取消。
- [ ] 联合发布的不可自动回退边界必须早于任何原生 queue/scheduler/web producer 重新接写。当前脚本先启动这些服务，健康检查后才撤 EXIT 回退 trap；host source-sync mutex 不覆盖原生任务，不能将其解锁当唯一写入起点。接写前可以按精确 receipt 恢复，接写后出错应维护/HOLD并核对真实记录，不自动删字段、回旧镜像或声称业务已回滚。Finance 候选须同时进入精确源码 allowlist、approved_sources_after 和同一联合 receipt identity 校验；仅解除 overlay 禁令不足以实现联合发布。
- [ ] 固定发布脚本的**最早接写**是 candidate backend/frontend/websocket 启动，不是随后 maintenance off/source mutex unlock。窄 metadata/cache/完整 after-audit 必须先在 command-only runner 完成；新旧 serving/producers 与在途 web/RQ/source 的实际只读 quiescence 证明先于备份。复用 `DDLReceipt._save` 的文件+目录 fsync，在第一条 web/RQ/scheduler/source resume 命令前持久写不可逆 resume-intent。恢复函数读取 marker 必须早于旧 compose/image/schema rollback；marker 存在或不可读均 maintenance/HOLD、留证据、前向恢复。pre-resume rollback 也保持 command-only，验证后其首次旧 writer resume 同样先登记；覆盖 marker 前/后、web/worker/maintenance/health/source handoff/SIGKILL，不能通过 purge/registry cleanup 伪造 drain。唯一发布负责人已确认此边界，尚无 runtime/deploy 验收。
- [ ] 2026-10-09 用户明确追加部署后服务器缓存清理：纳入同一唯一发布负责人的串行收尾，不另开维护执行者。发布前必须核对实际磁盘可用量及备份/构建/切换预算，空间不足停止；现有脚本未核实空间前检，不以目录名或可回收总量代替精确目标。发布后只清理确认可再生成、未使用的下载/构建缓存，按原生元数据证明 InUse/Shared/使用时间；不全局 system prune、删 volume、业务恢复备份、日志、附件、数据库或仍运行/需要恢复的镜像。记录清理目标与回收量，复核镜像/数据保持、磁盘、Redis、队列和 ERP 健康。备份保留策略尚未确认，须另行核实授权，不能当缓存删除。
  - 已核查现有 `deploy_unified_purchase.sh` 的同一 flock/release_dir、运行版本/源码/业务 audit 及 `tests/test_unified_purchase_release.py` 的 shell stub/recovery 用例可复用。现有 bench clear-cache 仅为运行缓存失效，并非磁盘清理；解包、build、带附件 backup 前缺空间预算检查。只在同一发布入口补实际文件系统余量/预算和验收后有界收尾，清理失败不重新进入已接写后的业务回退；沿现有 tests 补不足/未知预算、InUse/Shared/近期缓存拒绝、镜像保持及清理失败。未实施清理代码或生产清理，不新增第二维护流水线。
