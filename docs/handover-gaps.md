# 交接缺口清单（海外采购综合成本核算）

适用目录：本 app 仓库根（`overseas_costing` / 分支 `overseas_costing`）

本文件是**交接基线**：截至 2026-09-28 已核实的"还差什么"。所有结论都给了可复现的核实方法，
可以照着重跑一遍确认，不要只信描述。

---

## 0. 一句话结论

主干链路（费用与凭证、资料页、成本核算、ERP 站点化推送的**服务端**)已完工并在线上可用；
**差的是"多站点 ERP"这条线的前端与三个后续 Task**，以及一批不影响运行但会咬人的技术债。
业务数据侧仍然**一次正式推送都没有发生**（`confirm_status` 全 0），所以上线状态是"能力已通、业务未启用"。

---

## 1. 未完成的功能

### 1.1 多站点 ERP 同步界面（计划 Task 10）——完全没做

- 计划里要新建的 `parts/79-erp-sites.js`、`parts/51-erp-sites.css` **不存在**。
- 前端只调用 4 个旧入口：`confirm_calculation_result`、`preview_erp_payload`、
  `writeback_to_erp`、`check_writeback_ready`（见 `parts/30-calculation-erp.js`）。
- 服务端已就绪但**没有任何界面**：`preview_site_sync_plan`、`save_site_sync_plan`、
  `get_site_sync_requests`、`verify_erp_site_capability`、`reconcile_erp_request`、
  `retry_erp_request`（后两个是 2026-09-28 新增的核对/重试）。
- 后果：站点级预览、差异确认、部分成功只重试失败站点、`MANUAL_REQUIRED` 展示，
  目前只能通过 API / 控制台调用，业务同学看不到。

核实：
```bash
ls overseas_costing/page/overseas_cost_workbench/parts/ | grep -E "79-erp|51-erp"   # 无输出
grep -rn "preview_site_sync_plan\|get_site_sync_requests\|reconcile_erp_request" \
  --include=*.js overseas_costing/page/overseas_cost_workbench/parts/                # 无输出
```

### 1.2 暂估转实际（计划 Task 7）——只有开关，没有实现

- `cost_update_mode` 字段被读出来展示（`erp_capability_service.py:50`、`erp_sync_plan_service.py:276`），
  默认值 `DISABLED`，但**没有任何代码消费它去更新远端成本**。
- 计划要求的 `build_draft_purchase_cost_update` / `update_purchase_cost` / `preview_cost_updates`
  在全仓库**零命中**。
- 后果：只要将来启用"先按暂估推送、之后再改成实际成本"，远端采购单不会跟着改，
  只能人工处理，且系统不会给出待办。

核实：
```bash
grep -rn "update_purchase_cost\|preview_cost_updates\|build_draft_purchase_cost_update" \
  --include=*.py --include=*.js . | grep -v node_modules    # 无输出
```

### 1.3 站点级 ERP 待办与状态摘要（计划 Task 8）——只有批次级投影

- 现状是批次级 `writeback_status/writeback_time/writeback_message/erp_target_doc` 四个字段（全库仍 'Not Started'）。
- 计划要求的 `erp_work.overall / erp_work.sites[]`（按站点算 `SYNCED` / `UPDATE_REQUIRED` 与
  `ERP_UPDATE_REQUIRED` 待办）**不存在**。
- 后果：多站点时"哪个站点没同步"看不出来；费用待办与 ERP 回执的边界也没在代码里固化。

核实：
```bash
grep -rn "erp_work\|ERP_UPDATE_REQUIRED" --include=*.py --include=*.js . | grep -v node_modules   # 无输出
```

### 1.4 历史迁移（计划 Task 11）——未做

- 没有 `legacy_link_status`；旧批次不会被标 `UNVERIFIED`，也不会只读核验后补 VERIFIED 关联。
- 影响面目前很小：线上 `Purchase Order` 里 `custom_overseas_business_key` 非空 0 条
  （571 张全是 2026-05-25 批量导入的历史单，没有幂等键），所以**暂时没有"历史单被误关联"的风险**。
  真正需要迁移的是**本系统自己的旧批次**（见 2.6）。

### 1.5 批量设置项目归属：只能"一个值套所有选中行"

- 用户口径（2026-09-24）：987 行的正确归属**每行都不一样**，需要的是"弹窗内逐行指定、一次提交"。
- 现状：`openProjectCollectionPicker` 只维护**一个** `model.selectedValue`，
  确认后 `applyProjectCollectionSelection(items, target, ...)` 把所有选中行都写成同一个值。
- 后果：982+ 行只能一行行点，或先全选套一个错值再逐行改。

核实：`parts/78-material-fee-workspace.js:1474-1515`（单选 `selectedValue`）、
`applyProjectCollectionSelection(items, target, ...)`。

### 1.6 业务数据：能力通了但业务没启用

2026-09-28 线上实测（只读）：

| 指标 | 值 | 含义 |
| --- | --- | --- |
| 批次总数 | 146 | |
| 批次 `confirm_status=CONFIRMED` | **0** | 推送门槛③ 100% 阻断 |
| ERP 同步请求（账本） | **0** | 正式推送从未发生 |
| ERP 单据关联 | **0** | 没有行级关联记录 |
| ERP 站点 | **0** | 只有默认站点 `DEEPLINKERP` 可用 |
| 项目路由 | 10 | 见下 |
| 物料行 | 1451 | |
| 已填项目归属的行 | 990 | 其中**只有 3 行**能匹配到路由键 |
| 已填供应商的行 | **0** | 历史缺失由采购补填（用户已明确"不用管"） |
| 已推送的行（`purchase_order_no`） | **0** | |

- 990 行归属共 **14 个取值**，其中 `LatinGo拉丁购`(1) + `YW MOLDES MX模具`(2) = 3 行命中路由；
  剩 **987 行分布在 12 个取值上完全不可路由**，且这 12 个都是**产品线/客户**而不是项目归属：
  `productos comerciales贸易产品`(421)、`YW OEM-Tablet平板`(224)、`YW ODM`(160)、
  `YW OEM-IML Phone Case`(80)、`YW OEM-Phone Case`(29)、`YW OEM Soporte…车载支架`(26)、
  `超队1.0项目`(24)、`URIEL PÉREZ TORRES`(12)、`TK宠物用品项目`(4)、`亮甲2.0项目`(4)、
  `LA CASA`(2)、`Silicona Phone Case硅胶`(1)。
- 路由表 10 行（`project_collection → subsidiary_code` + `warehouse`），**`erp_site` 列全部为空**
  ⇒ 全部走默认站点。`warehouse` 全部有值（缺 warehouse 是行级硬阻断，所以这点是好的）。
- 结论：要真正推一次，前置是"确认计算（`confirm_status`）"＋"逐行重选项目归属"＋"补供应商"。

核实：`tmp/oc_ssh.py` + `tmp/_data_probe.sh`（本仓库未跟踪，见 2.8），或按第 5 节的命令重跑。

---

## 2. 已知技术债（不影响运行，但会咬人）

### 2.1 写令牌闸口有 10 处旁路（重要）

`acceptBatchWriteRevision()` 是 `expectedModified` 的**唯一合法入口**（令牌只前进不回退。
用快照里落后的 `header.modified` 当令牌会把 revision 拉回过去，之后本页每次写入都被乐观锁拒绝 417）。
全仓库仍有 **10 处直接赋值**绕过它：

| 文件 | 行 |
| --- | --- |
| `parts/100-crud-edit.js` | 437 |
| `parts/30-calculation-erp.js` | 332 |
| `parts/50-import-category.js` | 416 |
| `parts/65-manual-documents.js` | 896 |
| `parts/78-material-fee-workspace.js` | 3485、6272 |
| `parts/82-detail-page.js` | 66、133、599 |
| `parts/87-freight.js` | 463 |

这几条路径都从 `result.batch_modified` 取值，**当前恰好是前进的**，所以没爆；
但这是"逻辑正确靠运气"，任何一处改成回落到旧值就会复现"两个选择器点保存没反应"。

### 2.2 孤儿函数

- `erp_routing_service.preview_bulk_route()`（`:331`）：除自己的测试外无调用方。
  要么接进界面（计划里"整柜快捷归属"会用它），要么删掉。

### 2.3 部署链的顺序依赖没根治

- `deploy-overseas-costing.yml` 第 7 步 `docker image prune --all --force` 在 preflight **之前**跑。
  它删掉所有**未被容器引用**的镜像。于是"compose 的 tag 改了、但容器还跑着旧 tag"的窗口里，
  新 tag 的镜像会被当垃圾删掉，紧接着的 preflight 就失败（2026-09-28 实际踩到）。
- 已在 preflight 里加了**明确报错**（哪个镜像缺失、哪个文件声明的、怎么恢复），
  但"prune 不该回收 compose 引用的镜像"这件事**没有根治**。根治的代价是项目镜像会累积占盘，
  需要运维拍板。

### 2.4 多站点没有实测

- `Overseas Cost ERP Site` 0 条 ⇒ 只验证过默认站点 `DEEPLINKERP`。
  要加第二个站点，**必须先建这条记录**（`_load_site_config()` 对非默认站点才读该表；
  默认站点走 `Overseas Cost ERP Settings` 单例）。
- 由此，"多公司天然拆单"“分站点部分成功”这些分支**没有生产验证**。

### 2.5 目录索引文档严重滞后

| 文档 | 收录 | 实际 |
| --- | --- | --- |
| `overseas_costing/services/README_服务目录说明.md` | 10 行 | 82 个 `.py` |
| `overseas_costing/api/README_API目录说明.md` | 5 行 | 17 个 `.py` |
| `overseas_costing/doctype/README_DocType目录说明.md` | 13 行 | 23 个目录 |
| `overseas_costing/tests/README_测试目录说明.md` | 16 行 | 169 个 `.py` |

尤其是 **ERP 同步 8 个服务文件完全没有文档入口**（`erp_client` / `erp_routing_service` /
`erp_site_service` / `erp_sync_service` / `erp_sync_ledger_service` / `erp_sync_plan_service` /
`erp_capability_service` / `erp_sync_*`）。新人只能靠 `docs/superpowers/plans/2026-09-07-multi-site-erp-sync.md`
反推。本次已补 services 一版（见第 4 节）。

### 2.6 本地测试基线有 62 条红，且与 CI 不一致

本机全量：**62 failed / 4438 passed / 1 skipped / 4分56秒**。

- 全部集中在经理域：`test_material_ai_fill_service`（约 25 条）、`test_material_ai_payment_match`、
  `test_material_ai_context_fingerprint`、`test_material_ai_semantic_fee_proposals`、
  `test_shipment_review_integration`、`test_source_goods_value_adoption`、`test_unified_oa_fee_sync`。
- 这些用例**可单独复现**（不是测试间污染），但 **CI 上同批是绿的**（2026-09-24 与 09-28 两次都绿）。
- 已知环境差异：本机没有 `frappe` / `psycopg` / `minio` 模块；`test_additive_release_rollback.py`
  里 `subprocess` 调 `bash` 被安全策略解析到 `wsl.exe` 并拦截（该文件本机基线就是 2 failed / 1 passed）。
- **具体成因没有定位**。交接建议：**不要用本机红判断 CI 会红**；判断回归只看失败清单里有没有自己改的文件。

### 2.7 仓库外的基础设施不受版本管理（最大运维隐患）

宿主机 `/home/yuewei/ERPNext-Docker/frappe_docker/` 是 **上游 `frappe/frappe_docker` 的克隆**
（`origin=https://github.com/frappe/frappe_docker`），但下面这些**关键文件是本地改动、不在任何版本控制里**：

- `compose.custom.yaml`（镜像 tag、端口、卷、service 定义）
- `apps.json`（钉死 12 个分支，见 3.6）
- `upgrade_bench.sh`（真正执行 `docker build --no-cache` + `compose up --force-recreate` 的脚本）

后果（2026-09-27 实际发生）：有人手工把 compose 的镜像行 pin 成
`deeplinkerp-custom:v16.23.0-f33f7bc`（= 分支 `china_finance` 的 HEAD 前缀），
于是我们的流水线**全部步骤绿、`release_id` 前进、但容器重建后跑的还是旧代码**。
另外 `upgrade_bench.sh` 第 5 步会 `| tail -n +3 | xargs rm -f`，
**只保留最近 2 份 compose 备份** ⇒ 出事后可回看的现场很快就没了。

### 2.8 排查用探针不在版本控制里

`tmp/` 被 `.gitignore`，本会话用来核实线上状态的脚本（`oc_ssh.py`、`oc_run_probe.py`、
`tmp/_data_probe.sh`）都不在仓库里。交接时需要**重建**这套探针思路（做法见第 5 节），
否则接手人拿到 SSH 也不知道怎么查。

### 2.9 其它

- 前端脚本缓存在 `localStorage["_page:overseas-cost-workbench"]`（`pageview.js` 无过期机制）；
  `/assets/...` 恒 404，**不能用它判断部署是否生效**。已有持久锚点 `ocw_workbench_release` 自愈，
  但之前已缓存的用户需要手工 `localStorage.removeItem('_page:overseas-cost-workbench')` 再刷新。
- `parts/` 是**源**，`overseas_costing/scripts/build_workbench_assets.py` 合成 4 个产物
  （源目录 + 部署目录各两份）。**改了 `parts/` 必须重跑构建**；`parts/` 是类体片段，不能单独 `node --check`。
- 构建写 LF 而 `core.autocrlf=true` ⇒ 产物常显示 `M`，但 `git diff --ignore-cr-at-eol` 为空，
  纯 EOL 差异提交前 `git checkout --` 掉即可。
- `expectedModified` 之外，`route_status`/`subsidiary_code`/`erp_site_code` 是**残留字段**
  （全库无写入点），真实解析在 `build_site_sync_plan() → resolve_item_routes()` 实时覆盖。
  **不要用 DB 里这三个字段判断能不能推**。

---

## 3. 交接清单（要移交的东西）

### 3.1 代码与分支

- 仓库：`yueweiit/DeepLinkERP`，本线分支 **`overseas_costing`**（当前 HEAD 已上线）。
- 本 app 目录就是仓库根的这些：`overseas_costing/`、`docs/`、`.github/`、`setup.py` 等。
- 计划与设计文档：`docs/superpowers/plans/2026-09-07-multi-site-erp-sync.md`（11 个 Task 的原始设计）、
  `docs/superpowers/specs/2026-09-07-materials-fees-erp-design.md`（ERP 设计）、
  `docs/source-field-priority.md`（来源字段优先级，业务口径真源）。

### 3.2 GitHub Actions 密钥（缺一个就 red）

| Secret | 用途 |
| --- | --- |
| `DEPLOY_HOST` | 部署目标主机 |
| `DEPLOY_USER` | SSH 用户（`yuewei`） |
| `DEPLOY_SSH_PRIVATE_KEY` | SSH 私钥 |
| `DEPLOY_KNOWN_HOSTS` | host key 校验 |
| `DEEPSEEK_API_KEY` | 部署时写入站点配置，供 AI 解析/填充使用 |

工作流会显式检查前 3 个 + `DEEPSEEK_API_KEY` 非空，缺失即失败。
触发条件：**push 到 `overseas_costing` 分支即自动部署**，或手工 `workflow_dispatch`。

### 3.3 服务器

- `ssh yuewei@155.138.234.129`，工作目录 `/home/yuewei/ERPNext-Docker/frappe_docker`。
- **共享宿主**：同一台机器还跑着 `deeplink-mes-*`、`shop-crm-*`、`oem-crm-*` 等其它项目栈，
  动 Docker/磁盘前先确认影响面。
- 一个 bench 挂 **4 个 site**：`deeplinkerp.com`（**唯一**装了 `overseas_costing`）、
  akivision / latingo / yuewei。**"线上看不到 X" 先确认两边是不是同一个站。**
- `deeplinkerp.com` 另有 19 个账号被 `User Permission(allow=Company)` 限定只看得到 1 家公司，
  该限制**只作用于 `Company` doctype**，不级联海外采购链路。

### 3.4 运行时依赖

- compose service：`backend` / `queue-short` / `queue-long` / `scheduler` / `frontend` / `websocket` / `db` / `redis-*`。
  **`scheduler` 和两个 queue 容器必须活着**，否则：
  - `queue-long`：AI 填充/解析任务（`frappe.enqueue(..., queue="long")`）不会执行；
  - `scheduler`：4 条 cron 不跑（每 10 分钟的待办恢复、每天 8/18 点的装箱目录刷新、
    每 6 小时的审批修复与物流同步、每周日的对账）。
- 文档解析运行时（**部署脚本会在部署时重建并校验**）：`pdftotext` / `pdftoppm` / `tesseract` / `antiword` + `chi_sim`。
  2026-09-28 手工在宿主重建过容器，运行时被弄丢过一次，跑完流水线才补回来。

### 3.5 前端构建

```bash
python overseas_costing/scripts/build_workbench_assets.py
```
改了 `parts/` 必须重跑，否则线上还是旧的。

### 3.6 ⚠️ 共享镜像：13 个 app / 12 个分支

宿主的 `apps.json` 把 **12 个 app 都钉在同一个 fork 仓库 `yueweiit/DeepLinkERP` 的 12 个分支**上
（`erpnext`、`mes_integration`、`ai_assistant`、`deeplinkerp_branding`、`crm_integration`、
`custom_filters`、`draft_notifications`、`oa_purchase_request`、`client_akivision`、
`china_finance`、`overseas_costing`、`mobile_operations`），加上 `frappe` 共 13 个 app 烘在一个镜像里。
镜像构建容器 `Containerfile` 最后会 `find apps -mindepth 1 -path "*/.git" | xargs rm -fr`，
所以**容器里的 app 不是 git 仓库，代码完全由镜像决定**。

由此产生两个必须知道的风险：

1. **我们的部署会连带发布别人**：`upgrade_bench.sh` 用 `docker build --no-cache` 重新拉取这 12 个分支的
   **当前 HEAD**。哪怕我们只改了一行文档，重建镜像也会把其它分支的最新提交一起带上线
   （**包括 `erpnext` 这个 ERP 核心**）。
2. **别人的部署会覆盖我们**：任何人在同一台机器上重建/切换这个镜像，都会换掉我们的
   `apps/overseas_costing`。2026-09-27 的 pin 就是这种外力。

**建议：纯文档类改动不要单独推上去触发重建**，攒到下次有功能性改动时一起走。

### 3.7 线上版本判定（两个口径，blob 更硬）

```bash
# 口径一：发布标识
docker compose -f compose.custom.yaml exec -T -w /home/frappe/frappe-bench/sites backend \
  bench --site deeplinkerp.com show-config | grep overseas_costing_release_id
```
注意：**只有 `show-config`，没有 `get-config`**。而且 `release_id` 会在"绿着发不出去"时
前进到新提交却跑旧代码（见 2.7）⇒ **必须配合口径二**：

```bash
# 口径二：对容器内文件做 blob 哈希，与本地提交逐字节比
docker exec frappe_docker-backend-1 sh -lc \
  "cd /home/frappe/frappe-bench/apps/overseas_costing && git hash-object <path>"
git rev-parse <sha>:<path>     # 本地对照
```

### 3.8 线上排查入口

- **`tabError Log`**：Frappe 会把浮出的异常连**局部变量（含 API 入参）**一起记下来（该表无 `title` 列）。
  排查线上写入失败第一步就看它。
- 快照读的是服务端 store 的 blob：`get_snapshot` 只要有 `data` 且 schema 匹配就
  `served_from_cache: true` 直吐（**不判 stale**），前端靠 `check_freshness` 的指纹决定要不要重建。
- 快照重建曾经要 4.2s（92~95% 是跨网查 OA，**与行数无关**），已按「批次 + 来源/关联实例」指纹
  缓存进 Redis（非空 300s / 空 30s）⇒ 实测 3.8~4.3s → **0.13~0.42s**。
  用户感知的"保存太慢"其实是保存后 `cacheDirty` 触发的那次重建（保存本身只 ~200ms）。

### 3.9 分工边界（现状）

- **本线（我们）**：费用与凭证 /「关联并解析凭证」链路；前端 `parts/78-material-fee-workspace.js`
  + `parts/48-material-fee-workspace.css`；ERP 同步服务端。
- **经理**：前端整体优化 + AI 填充（`material_ai_fill_service.py` 等），他自己合分支。
- 约定：只提交自己地盘的产物；碰到别人地盘的 bug 要先说明覆盖面再动手。

---

## 4. 本次审计顺手修掉的小事

- `overseas_costing/services/README_服务目录说明.md`：补上 ERP 同步 8 个服务与其余主要模块的索引
  （原表只列了 10 个）。
- 仓库根目录文件名乱码的 `README_应用目录说明.md`（原文件名是 GBK/UTF-8 二次误读后的乱码，
  含私用区字符）→ 改回正常文件名，并把过时的目录清单更新到当前结构。

---

## 5. 复现审计结论的方法

```bash
# 1) 本机全量测试（约 5 分钟）
export PATH="/c/Users/lin/.workbuddy/binaries/node/versions/22.22.2-3:/usr/bin:/bin:/e/Git/cmd:/c/Windows/System32:$PATH"
cd <repo>
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python -m pytest overseas_costing/tests -q \
  -p no:cacheprovider --basetemp=.pytest_tmp
# 期望：62 failed, 4438 passed（红的都在经理域，CI 上是绿的）

# 2) 线上只读核实（需要 SSH 口令）
OC_HOST=<host> OC_USER=<user> OC_PW=<pw> python tmp/oc_ssh.py   # 以 bash -s 模式管道喂脚本
#   常用查询：
#   - 发布标识：docker compose ... bench --site deeplinkerp.com show-config | grep release_id
#   - 账本/数据：容器内 `env/bin/python -` 跑 frappe.init + frappe.db.count（不要用 bench mariadb --execute 转义）
#   - 镜像与容器：docker images | grep deeplinkerp ; docker ps --format '{{.Names}}\t{{.Image}}'
```

---

## 6. 建议的后续优先级

| 优先级 | 事项 | 理由 |
| --- | --- | --- |
| P0 | 把 `apps.json` / `compose.custom.yaml` / `upgrade_bench.sh` 纳入版本控制（或至少归档到仓库 `deploy/`） | 唯一能让"绿着发不出去"重演的东西，且现场备份会被自动删 |
| P0 | 决定是否根治「第 7 步 prune 与 compose tag 的顺序依赖」 | 需要运维拍板，事很小但会反复咬人 |
| P1 | 多站点 ERP 前端（Task 10） | 服务端 6 个 API 已经就绪，只差界面；否则"多站点"等于没上线 |
| P1 | 批量设置项目归属支持逐行指定 | 987 行卡在这，是启用推送的实际前置 |
| P1 | 补供应商（业务动作，采购侧） | 1451 行全空，同样的推送前置 |
| P2 | Task 8 站点级待办/状态摘要 | 多站点上线后立刻会需要 |
| P2 | Task 7 暂估转实际 | 只在业务决定"先暂估后改实际"时才需要 |
| P3 | 10 处 `expectedModified` 旁路收口、`preview_bulk_route` 处理、目录文档补全 | 防止回归与降低接手成本 |
| P3 | Task 11 历史迁移 | 当前 ERP 侧无历史幂等键，风险很低；本系统旧批次另论 |
