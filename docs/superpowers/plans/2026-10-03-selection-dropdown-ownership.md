# 全站选择框归属迁移 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task.

**Goal:** 将已有全站选择框能力归入 deeplinkerp_branding，Overseas 同次退出，只准备可合并提交，不触发生产发布。

**Architecture:** 复用已冻结 JS 和原 135 个测试，不修改选择行为或原生权限查询。Branding 使用现有 Desk 静态资源注册；Overseas 删除旧资源、测试副本和注册，两个提交由单一发布负责人配套切换。

**Tech Stack:** Frappe Desk JavaScript、pytest/Node、现有应用 hooks 与共享 Docker 发布。

## 基线和边界

- Branding 基线 `4450e129df44cd2734398c8586641cbaf87989c7`；库存 pytest 基线 52 通过。
- Overseas 基线 `713fa5b4a4428288a867737285b356793a0666a2`。
- 复用来源 `/Users/smk/.codex/worktrees/selection-dropdowns/DeepLinkERP`；冻结 JS SHA256 `130fd9f58489dbfc187100bd149668c4c9df0503f7e8f8d8907de67281509901`。
- 保留 Branding 库存资源、安装升级钩子和页面；采购导航/列表 hooks 由发布负责人增量合并，禁止覆盖整份 hooks。
- 不 push overseas_costing，不 workflow dispatch，不调用生产 migrate、库存转移或公司数据修改。生产切换负责人为“评估ERP凭证生成流程”对话。

## Task 1: Branding 接管

- [ ] 迁移原 pytest 模块至 `deeplinkerp_branding/tests/test_selection_dropdown_frontend.py`，ROOT/HARNESS/hooks 指向 Branding；harness 仍以 `../../public/js/selection_dropdown.bundle.js` 读取真实资源。先运行单击浏览和注册用例，确认缺少实现和注册导致失败。
- [ ] 原样迁移 JS 至 `deeplinkerp_branding/public/js/selection_dropdown.bundle.js`，原样迁移 harness 至 `deeplinkerp_branding/tests/frontend/selection_dropdown_harness.js`。仅在现有 `app_include_js` 加入 `/assets/deeplinkerp_branding/js/selection_dropdown.bundle.js`。
- [ ] 注册用例以 AST 读取 hooks，断言新资产恰好一次并保留原库存资源；不再检查 Overseas 的正向注册。
- [ ] 运行 `python3 -m pytest -q deeplinkerp_branding/tests`（预期 187 通过）、两个 JS 的 `node --check` 和 `git diff --check`；核对冻结 JS 哈希未变。
- [ ] 规格审查通过后进行质量审查；提交 Branding 增量，不发布。

## Task 2: Overseas 退出

- [ ] 在 `overseas_costing/tests/test_selection_dropdown_ownership.py` 写 AST/文件回归，要求旧加载入口和三份旧实现/测试文件均不存在；先运行证明现有入口和副本使其失败。
- [ ] 删除旧 hooks `app_include_js` 注册、旧 JS、旧行为 pytest 模块和旧 harness。没有已知独立调用者，无需兼容副本；Branding 注册配套生效后旧资产不再需要。
- [ ] 运行新退出回归及 Overseas 全量本地 pytest、`git diff --check`，区分原有跳过和失败。
- [ ] 规格审查通过后进行质量审查；提交 Overseas 退出增量，不 push。

## Task 3: 联合交付

- [ ] 报告两个提交、冻结源哈希、真实测试与静态调用检索；报告新增/修改/删除、重复逻辑、代码/测试数量变化和未处理技术债。
- [ ] 交付既有 CI 固定 Branding SHA/内容摘要的准确计算方式，提示旧发布包含历史业务写入和代码回滚不等于数据回滚；不自动修改固定目标或跑旧流程。
- [ ] 交付线上未验项：采购表头、物料和仓库明细；Dynamic Link/MultiSelect 仅自动化覆盖。限定覆盖后由发布负责人核对只加载一份 Branding 脚本、原值取消保留及真实权限过滤；不得据本地测试宣称线上验收完成。
