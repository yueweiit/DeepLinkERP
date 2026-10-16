# ERP 分支与对接说明

## 同事应该上传到哪里

采购、销售、库存、导航和共享界面服务统一使用 `deeplinkerp_branding`，也是 GitHub 默认分支。
从该分支拉取当前代码，开发修改后提交到该分支的 PR；不要从历史 `codex/*` 分支继续建立协作基线。

仓库中的其他应用分别使用固定入口：

- CRM 销售订单、销售出库及 CRM 接口：`crm_integration`。
- 中国财务和凭证：`china_finance`。
- OA 采购申请及审批接入：`oa_purchase_request`。
- 海外成本核算：`overseas_costing`。

这些分支是独立的 Frappe 应用代码树，不能把一个应用的整棵分支直接覆盖另一个应用。
对接 ERP 的同事应按实际修改的应用选择入口；跨应用修改拆成相应应用的 PR，并标明彼此依赖。

## 取得 ERP 界面主线

```bash
git fetch origin
git switch deeplinkerp_branding
git pull --ff-only origin deeplinkerp_branding
git switch -c feature/your-change
```

新克隆仓库会默认检出 `deeplinkerp_branding`。已有未提交修改先正常提交或保存，再更新自己的工作区；不要使用强推或重置覆盖同事工作。
PR 的目标选择 `deeplinkerp_branding`；完成合并后删除本人临时功能分支，长期应用主线保持固定名称。

## 本次基线如何确定

本次按用户确认，以服务器正在运行的版本为准。Branding 应用代码来自 `3ff92df60f67d1cd76e79e2d063bd44b71a8a410`。
原默认分支中的三个独有提交保留在 Git 合并历史中，本次不将其尚未在线上的应用改动带入协作基线。
同时保留已验证的 CRM 发布工具 `289690cd45944a3ccbfe8fb8e100c2fc1fe9791d`；它们不修改运行中的接口。

线上 ERP 镜像包含多个应用的冻结版本，具体提交见根目录 `PRODUCTION_BASELINE.json`。
CRM、财务、OA 分支的最新提交不代表已经部署；涉及这些接口时，以该文件的生产提交和实际在线接口为核对依据。
OA 当前生产提交尚未在 GitHub 查到，必须保留本地 `codex/explicit-purchase-receipts` 及发布证据，完成远端归档后才能清理该本地分支。

## 验证与发布

提交 PR 时运行对应应用现有测试，集成修改另外验证接口的请求、响应、权限、幂等键和来源关联。
本次整理不调整接口路径、字段、数据库结构或业务数据，也不触发服务器部署。
后续发布仍走现有发布锁、冻结提交、健康检查和业务页面验收，并在验收后更新生产快照。
