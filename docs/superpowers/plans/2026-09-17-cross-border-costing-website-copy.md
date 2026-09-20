# 跨境综合成本官网文案 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 产出一份可直接拆分到官网产品页的中文销售文案。

**Architecture:** 文案以经营结果为主线，用已验证的系统能力支撑价值主张，再用老板、财务、采购物流和 IT/ERP 四类角色的收益完成购买论证。交付是独立 Markdown 正文，不包含网页代码。

**Tech Stack:** Markdown；仓库内现有产品文档、DocType 和服务实现作为事实依据。

---

### Task 1: 起草官网正文

**Files:**
- Create: `docs/product/cross-border-costing-website-copy.md`
- Reference: `docs/superpowers/specs/2026-09-17-cross-border-costing-website-copy-design.md`

- [x] **Step 1: 写首屏、问题与经营价值**

先回答买方“为什么要买”，不以功能清单开场。

- [x] **Step 2: 写业务链、系统能力与连接说明**

按“采购与审批 → 装箱与出货 → 国际物流 → 付款与费用证据 → 成本分摊 → 利润分析 → ERP”组织内容。

- [x] **Step 3: 写四类角色价值、落地流程与行动号召**

每类角色给出可理解、可验证的购买依据，结尾邀请客户用真实批次进行试算或流程评估。

### Task 2: 事实与文案质量校验

**Files:**
- Modify: `docs/product/cross-border-costing-website-copy.md`
- Reference: `HANDOFF.md`
- Reference: `docs/air-sea-cost-comparison.md`
- Reference: `docs/packing-sheet-cache-operations.md`
- Reference: `docs/logistics-settlement-operations.md`
- Reference: `docs/shipment-value-project-freight.md`

- [x] **Step 1: 扫描夸大和未实现表述**

确认不宣传未实现的电商平台连接、自动付款、自动记账、AI 自动确认或虚构的收益数据。

- [x] **Step 2: 检查购买者阅读路径**

确认不阅读技术细节也能理解经营价值；财务、采购物流与 IT 读者能找到各自的评估依据。

- [x] **Step 3: 执行文字自检**

运行：`rg -n "TBD|TODO|百分之|自动付款|自动记账|Amazon|Shopify" docs/product/cross-border-costing-website-copy.md`

预期：不出现占位符、虚构收益或未实现连接；如有命中，仅能出现在明确的能力边界说明中。

### Task 3: 交付

**Files:**
- Read: `docs/product/cross-border-costing-website-copy.md`

- [x] **Step 1: 检查 Markdown 结构与差异**

运行：`git diff --check -- docs/product/cross-border-costing-website-copy.md`

预期：命令无输出并且退出码为 0。

- [x] **Step 2: 在对话中交付完整正文**

提供可点击的 Markdown 文件链接，并直接给出可复制到官网开发对话的完整文案。
