# ERP 分支与对接说明

## 同事应该上传到哪里

采购、销售、库存、导航和共享界面服务统一使用 `deeplinkerp_branding`，也是 GitHub 默认分支。
从对应应用的固定分支拉取当前代码，开发修改后提交到该分支的 PR；不要从历史 `codex/*` 分支继续建立协作基线。

仓库中的其他应用分别使用固定入口：

- CRM 销售订单、销售出库及 CRM 接口：`crm_integration`。
- 中国财务和凭证：`china_finance`。
- OA 采购申请及审批接入：`oa_purchase_request`。
- 海外成本核算：`overseas_costing`。

这些分支是独立的 Frappe 应用代码树，不能把一个应用的整棵分支直接覆盖另一个应用。
对接 ERP 的同事应按实际修改的应用选择入口；跨应用修改拆成相应应用的 PR，并标明彼此依赖。

## 同时修改三个部分时

ERP 页面改动提交到 `deeplinkerp_branding`，ERP 侧 CRM 接口改动提交到 `crm_integration`，财务改动提交到 `china_finance`；涉及 OA 申请和审批的代码另外提交到 `oa_purchase_request`。
各应用分别检出到独立目录或 worktree，并为同一次对接的 PR 标明依赖、接口字段和验收顺序。不要将不同应用的仓库根目录互相复制覆盖。
独立运行的 CRM 后端属于另一套仓库；这里的 `crm_integration` 是 ERP 侧接入应用，并非 CRM 网站后端源码。

## 取得应用主线

以下以 ERP 界面为例；修改其他应用时，将两个 `deeplinkerp_branding` 参数替换为上文对应分支：

```bash
git fetch origin '+refs/heads/*:refs/remotes/origin/*' --prune
git switch deeplinkerp_branding
git pull --ff-only origin deeplinkerp_branding
git switch -c feature/your-change
```

新克隆仓库会默认检出 `deeplinkerp_branding`。已有未提交修改先正常提交或保存，再更新自己的工作区；不要使用强推或重置覆盖同事工作。
PR 的目标选择对应的长期应用分支；完成合并后删除本人临时功能分支，长期应用主线保持固定名称。
如果旧功能分支在本次整理前已经开发，应从更新后的固定分支新建功能分支，再有选择地移植所需提交并重新测试；不要把归档版本整批合回来。

## 本次基线如何确定

本次按用户确认，以服务器正在运行的版本为准，四个应用的协作基线分别与生产源码一致。
2026-10-16 的生产提交保存在 `production/2026-10-16/<应用分支名>` 标签中；整理前的主线保存在 `archive/2026-10-16/<应用分支名>-before-production-alignment` 标签和合并历史中，没有强推或改写既有提交。
原默认分支中的三个独有提交，以及 CRM 主线尚未部署的订单修订改动，本次不带入协作基线；需要恢复时独立评审。
同时保留已验证的 CRM 发布工具 `289690cd45944a3ccbfe8fb8e100c2fc1fe9791d`；它们不修改运行中的接口。

线上 ERP 镜像包含多个应用的冻结版本，具体提交见根目录 `PRODUCTION_BASELINE.json`。
分支会随着后续开发继续前进，因此分支最新提交不自动代表已经部署；核对当前线上接口时，以该文件的生产提交、应用代码树和实际在线接口为依据。
OA 原先仅在本地保留的生产提交现已通过生产标签归档到 GitHub。

## 验证与发布

提交 PR 时运行对应应用现有测试，集成修改另外验证接口的请求、响应、权限、幂等键和来源关联。
本次整理不调整接口路径、字段、数据库结构或业务数据，也不触发服务器部署。
后续发布仍走现有发布锁、冻结提交、健康检查和业务页面验收，并在验收后更新生产快照。
