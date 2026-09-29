# 库存实际数量报表与原始库位追溯设计

日期：2026-09-29

## 目标

库存人员只查看实际库存，不在同一报表混入采购在途、预留、计划数量和重订货字段。报表固定展示：正式物料编码、双语名称、仓库、原始库位、物料组、汇总数量、库存单位、DPCI、外部编码、原始标识/别名。

## 复用优先结论

- 库存数量直接读取 ERPNext `Bin.actual_qty`，不复制库存计算逻辑。
- 物料、仓库、物料组、DPCI、外部编码直接复用 `Item`、`Warehouse` 及现有自定义字段。
- ERP 标准 `Stock Projected Qty` 保留，继续承担计划库存分析。
- `Bin.custom_original_location`、`Item.custom_original_identifier_alias` 和 Stock 工作区“可用数量”入口均属于 ERP 配置，直接在生产站点配置，不增加安装器、回填 API 或第二套配置流程。
- 仅“同一数量列按单位逐行显示 0 或 2 位小数”无法通过现有报表静态精度配置完成，因此保留一个最小 Script Report。

## 数据与显示

- 每行代表一个非零 `Item + Warehouse` 的 `Bin` 余额；停用物料若仍有库存也必须显示。
- 原始库位存入对应 `Bin.custom_original_location`，不创建 92 个货架子仓库。
- 原始编码去重后存入 `Item.custom_original_identifier_alias`；DPCI 和外部编码仍使用现有字段。
- `个、件、套、卷、包、张、片、支、条、台`等计数单位，整数库存显示 0 位小数。
- `kg`、`m²`等连续计量单位显示 2 位小数。
- 计数单位如出现小数，保留 2 位并标红提示，不静默改成整数。
- 底层数量保持数值类型，筛选、排序和导出不改为文本。

## 直接配置

1. 新建 `Bin.custom_original_location`（Data，只读，原始库位）。
2. 新建 `Item.custom_original_identifier_alias`（Small Text，原始标识/别名）。
3. 从盘点审计表回填 377 个 `Item + Warehouse` 原始库位和 375 个物料别名；两个色母粒使用最终编码 `FL007979`、`YL001974`。
4. 将 Stock 工作区现有“可用数量”链接改指 `Inventory On Hand`。

配置与回填不修改库存数量、单位、估值、Stock Ledger Entry 或已提交的 Stock Reconciliation。

## 代码边界

仅新增标准 Script Report `Inventory On Hand`：

- Python 查询 `Bin.actual_qty` 并返回约定的 10 列。
- JavaScript 只处理行级 0/2 位小数显示和异常提示。
- 不修改 ERPNext 核心报表，不新增自定义库存表，不新增写入接口。

## 验收

- YWFM 三个仓库共 377 条非零库存行，原始库位全部可见，92 个不同库位。
- 数量控制合计仍为 `746,610.49`，库存价值仍为 0。
- `FL007979` 为 `综合仓库 - YWFM / AI-4-C01 / 19.60 kg`。
- `YL001974` 为 `IML 仓库 - YWFM / AI-4-C01 / 7.51 kg`。
- 计数单位无无意义小数，kg/m² 为两位小数。
- 标准 `Stock Projected Qty` 仍能直接访问。
- 配置前后无新增库存流水或库存调账单。
