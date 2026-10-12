# 2026-08-03 PLM seeds 字段产品与 SKU 归档口径沉淀

## 1. 本次范围

本次只扫描和沉淀字段归档口径，不导入系统、不生成导入文件、不修改数据库。

扫描来源：

| 文件 | 主要内容 | 顶层规模 |
| --- | --- | ---: |
| `D:\work\资料\PLM\seeds\deployment_master_data_seed.json` | 品牌、机型、颜色、产品、SKU、BOM、物料、资源与产能基础数据 | `tables` 下 22 类对象 |
| `D:\work\资料\PLM\seeds\master_route_seed.json` | 产品级工艺路线、节点、边、节点配置 | 产品 7 条，路线 10 条 |
| `D:\work\资料\PLM\seeds\rule_config_seed.json` | 工序模板、拆分规则、报工模板、领料/产能/换型规则 | 规则 53 条 |

项目内同步副本位于 `D:\work\Yuewei\PLM\seeds`，本次字段解析使用该副本校验编码与中文内容。

## 2. 当前系统承接口径

当前系统核心承接对象仍是 `plm_product`，不是独立的 `plm_sku` 根表。后端产品实体已经预留这些关键字段：

| 系统字段 | 归档含义 |
| --- | --- |
| `product_code` | 产品或型号/SKU归档编码 |
| `parent_product_id` | SKU/型号归属的上级产品 |
| `product_type` | 当前稳定口径为 `product_line`、`model_variant` |
| `product_specific_code` | 产品特征码，用于生成模具、半成品、成品编码 |
| `phone_model_code` | 手机型号编码 |
| `color_code` | 颜色编码 |
| `finished_product_code` | 成品/SKU编码 |
| `import_short_code` | 外部短码或历史编码 |
| `series_name`、`model`、`color` | 展示与人工核对字段 |

因此本次建议先按两层沉淀：

| 层级 | 系统对象建议 | 主识别键 | 说明 |
| --- | --- | --- | --- |
| 产品层 | `plm_product.product_type=product_line` | `mes_product.product_code` / `master_route_seed.products.product_code` | 承接产品线、系列、多语言名称、别名、默认路线等稳定资料 |
| SKU层 | 暂以 `plm_product.product_type=model_variant` 承接，后续如有独立 SKU 表再迁移 | 优先 `article_code` / `sku_code` / `finished_product_code`，同时关联 `product_code + model_code + color_code` | 承接具体可销售/可生产的机型颜色版本；BOM、工艺、库存、订单都应落到这一层 |

## 3. 总体结论

1. `mes_product` 和 `master_route_seed.products` 是产品层主档的主要来源。
2. `mes_sku_master` 是 SKU 层主档的主要来源，数量最大，共 3830 条。
3. `bom_main.parent_code` 目前更像历史成品/BOM父项编码，适合归档到 SKU/型号层，并作为 BOM 版本头的拥有者。
4. `mes_phone_model_code`、`mes_color_code`、`mes_brand_code` 不直接成为产品或 SKU，但必须作为 SKU 归档前置字典。
5. `bom_child`、`mes_bom_process_mapping`、`mes_material_mapping_rule` 不进入产品/SKU主档字段，归档到 SKU 的 BOM明细、工序物料映射和历史追溯资料。
6. `master_route_seed.process_routes` 是产品层默认工艺路线模板，路线节点中的 `outputBaseCode`、`outputType`、`outputDimensions` 是后续按 SKU 生成半成品/成品编码的重要依据。
7. `rule_config_seed.json` 大多是工艺、排产、报工、领料规则，不应塞进产品/SKU主档；只保留规则编码与适用维度的关联。

## 4. 数据表归档矩阵

| seed 对象 | 行数 | 字段归档建议 | 产品层 | SKU层 | 备注 |
| --- | ---: | --- | --- | --- | --- |
| `mes_product` | 7 | 产品主档 | 是 | 否 | `product_code`、中英西名称、描述、状态、排序进入产品层 |
| `master_route_seed.products` | 7 | 产品主档补充 | 是 | 否 | 与 `mes_product` 互校验，补路线种子来源 |
| `product_alias_mapping` | 28 | 产品别名 | 是 | 否 | 作为产品搜索别名、历史名称映射 |
| `mes_sku_master` | 3830 | SKU主档 | 关联 | 是 | SKU层核心来源，按 `sku_code/article_code` 归档 |
| `bom_main` | 24 | SKU/BOM头 | 关联 | 是 | `parent_code` 作为型号/SKU归档候选；`bom_code + version` 成为 BOM 版本 |
| `mes_product_bom_binding` | 1 | SKU/BOM绑定规则 | 关联 | 是 | 可作为 SKU 到 BOM 的人工覆盖规则 |
| `mes_brand_code` | 17 | 品牌字典 | 否 | 前置字典 | SKU手机品牌维度 |
| `mes_phone_model_code` | 1157 | 手机型号字典 | 否 | 前置字典 | `model_code` 是 SKU 归档关键外键 |
| `mes_color_code` | 71 | 颜色字典 | 否 | 前置字典 | `color_code` 是 SKU 归档关键外键 |
| `mes_product_item_code` | 33 | 产品工序状态/半成品基础码 | 是 | 派生 | 不作为产品主档；用于产品路线和半成品编码 |
| `mes_product_item_color` | 73 | 半成品/成品可用颜色 | 是 | 派生 | 作为产品可生产颜色和 SKU 颜色候选 |
| `material_items` | 80 | 物料/库存主档 | 关联 | BOM使用 | 落库存物料，不进产品/SKU主档 |
| `bom_child` | 313 | BOM行项目 | 关联 | 是 | 归档到 SKU/BOM版本下的物料明细 |
| `mes_bom_process_mapping` | 311 | BOM物料到工序节点映射 | 关联 | 是 | 挂到 SKU 的 BOM工艺映射 |
| `mes_material_mapping_rule` | 83 | 物料映射规则 | 规则 | 规则 | 不进主档，供 BOM/工艺预览匹配 |
| `master_route_seed.process_routes` | 10 | 产品路线模板 | 是 | 实例化 | 产品默认路线，SKU按颜色/机型套用 |
| `rule_config_seed.operation_templates` | 14 | 工序库模板 | 工艺资料 | 工艺资料 | 不进产品/SKU主档 |
| `rule_config_seed.task_split_rules` | 13 | 任务拆分规则 | 工艺规则 | SKU生产规则 | `split_dimensions` 判断拆分到产品、机型、颜色哪一层 |
| `rule_config_seed.report_templates` | 6 | 报工模板 | 工艺资料 | 报工资料 | 按工序类型挂接 |
| `rule_config_seed.material_rules` | 8 | 领料规则 | 工艺资料 | 生产规则 | 按工序/仓库规则使用 |
| `rule_config_seed.capacity_rules` | 9 | 产能规则 | 工艺资料 | 生产规则 | 不写产品/SKU主档 |
| `rule_config_seed.changeover_rules` | 3 | 换型规则 | 工艺资料 | 生产规则 | 按工序和维度生效 |
| `mes_resource`、`mes_machine`、`mes_resource_capability`、`mes_machine_capacity` | 319 | 资源产能资料 | 否 | 生产排产关联 | 作为设备/资源能力主数据，不进入产品/SKU主档 |
| `mes_shift`、`mes_team`、`mes_employee` | 9 | 班次班组人员 | 否 | 生产排产关联 | `mes_employee` 当前为空 |

## 5. 产品层字段建议

### 5.1 产品主档

来源：`mes_product`、`master_route_seed.products`。

| seed 字段 | 建议归档位置 | 说明 |
| --- | --- | --- |
| `product_code` | `plm_product.product_code` | 产品层主键，例如 `NBA4030` |
| `product_name_cn` | `plm_product.product_name` | 中文产品名优先展示 |
| `product_name_en`、`product_name_es` | 产品扩展属性或备注 | 多语言名称，建议后续放产品多语言扩展表 |
| `product_type` | `plm_product.product_type` 映射为 `product_line` | seed 中为 `phone_case`，系统内不直接使用 |
| `description_zh/en/es` | 产品扩展属性或资料说明 | 不建议塞入 `remark` 长文本，可后续建产品说明字段 |
| `display_order` | 产品排序扩展 | 用于基础资料展示顺序 |
| `default_bom_code` | 产品默认BOM引用 | 当前多为空，后续可指向默认 SKU/BOM |
| `has_version`、`is_combo` | 产品扩展属性 | 判断是否组合产品或版本化产品 |
| `status` | `plm_product.status` | `enabled` 建议映射为 `archived` 或 `released`，具体看是否作为历史正式资料 |
| `source`、`remark` | `remark` 或来源扩展 | 保留来源 `crm/seed/excel` |

### 5.2 产品别名

来源：`product_alias_mapping`。

| seed 字段 | 建议归档位置 | 说明 |
| --- | --- | --- |
| `product_code` | 关联产品层 `product_code` | 必须先匹配产品 |
| `alias_name`、`alias_key` | 产品别名扩展 | 用于历史名称、搜索、导入匹配 |
| `is_enabled`、`status` | 别名状态 | 禁用别名不参与自动匹配 |
| `source`、`remark` | 别名来源与说明 | 保留人工核对依据 |

### 5.3 产品工序状态基础码

来源：`mes_product_item_code`、`mes_product_item_color`。

这两类数据不应直接变成产品主档，但应挂在产品层的“编码与生产资料”下。

| seed 字段 | 建议归档位置 | 说明 |
| --- | --- | --- |
| `product_series` | 关联产品系列 | 用于人工核对产品归属 |
| `base_code` | 产品工序状态编码基础码 | 例如 `NBA1010`、`NBA4030`；`4030` 通常指成品最终工序 |
| `process_name` | 工序名称 | 与工序库 `operation_templates` 对齐 |
| `material_type` | 材质或物料类型 | 参与模具/半成品/BOM判断 |
| `item_type`、`is_finished_goods` | 半成品/成品标识 | 判断该基础码是否用于 SKU 成品编码 |
| `color_code`、`color_name_zh/es` | 可用颜色 | 为 SKU 颜色候选，不等于已存在 SKU |

## 6. SKU层字段建议

### 6.1 SKU主档

来源：`mes_sku_master`。

| seed 字段 | 建议归档位置 | 说明 |
| --- | --- | --- |
| `sku_code` | `finished_product_code` 或 `import_short_code` | 如果与 `article_code` 一致，可作为 SKU历史编码 |
| `article_code` | SKU主识别键，优先归档为 `finished_product_code` | 订单、BOM、库存优先按该字段关联 |
| `product_code` | 上级产品 `parent_product_id` | 关联产品层，例如 `NBA4030` |
| `product_name` | SKU展示名称 | 可落 `product_name`，但不作为唯一匹配键 |
| `phone_brand` | SKU品牌维度 | 关联 `mes_brand_code` |
| `phone_model` | SKU机型展示名 | 文本展示和人工核对 |
| `model_code` | `phone_model_code` | SKU关键维度，应能反查 `mes_phone_model_code.model_code` |
| `color` | SKU颜色展示名 | 文本展示 |
| `color_code`、`color_short_code` | `color_code` | SKU关键维度，应能反查颜色字典 |
| `color_name_zh/en/es` | 颜色多语言快照 | 可作为SKU展示快照 |
| `material_type` | SKU材质 | 可落 `material` 或 SKU扩展属性 |
| `unit` | SKU单位 | 可用于库存/订单单位 |
| `version` | `version_no` | SKU版本 |
| `product_subtitle`、`available_colors`、`combo_name` | SKU扩展属性 | 不建议作为主键 |
| `bom_code` | SKU默认BOM引用 | 关联 `bom_main.bom_code` |
| `status`、`source` | 状态与来源 | `enabled` 代表可归档候选 |

SKU 唯一性建议：

| 优先级 | 唯一性依据 | 说明 |
| ---: | --- | --- |
| 1 | `article_code` | 外部系统成品/SKU编码优先 |
| 2 | `sku_code` | 当 `article_code` 缺失时使用 |
| 3 | `product_code + model_code + color_code` | 编码缺失时作为候选组合，必须人工确认 |
| 4 | `product_name + phone_model + color` | 仅人工核对，不自动建唯一关系 |

### 6.2 BOM父项与SKU关系

来源：`bom_main`、`mes_product_bom_binding`。

| seed 字段 | 建议归档位置 | 说明 |
| --- | --- | --- |
| `bom_main.bom_code` | SKU/BOM版本编码 | 进入 BOM 头，不作为 SKU 编码 |
| `bom_main.parent_code` | SKU/型号候选编码 | 当前转换脚本曾作为 `model_variant.product_code` 导入 |
| `bom_main.parent_name` | SKU/型号名称快照 | 仅展示和人工核对 |
| `bom_main.version` | BOM版本 / SKU资料版本 | 通常 `V1` |
| `bom_main.custom_bom_specification` | SKU颜色/规格快照 | 可辅助匹配颜色 |
| `bom_main.output_qty` | BOM产出数量 | 进入 BOM 头 |
| `bom_main.is_active` | BOM启用状态 | 映射 BOM 状态 |
| `mes_product_bom_binding.condition_json` | BOM绑定条件 | 保留人工覆盖原因 |
| `mes_product_bom_binding.priority` | 绑定优先级 | 多BOM候选时使用 |

建议口径：

1. `mes_sku_master.bom_code` 优先绑定 `bom_main.bom_code`。
2. 如果 SKU 没有 `bom_code`，再用 `product_code + color_code/model_code` 与绑定规则匹配。
3. `bom_main.parent_code` 不直接等同产品层产品编码，应视为历史成品/型号层编码。

## 7. SKU下属BOM与工艺资料

### 7.1 BOM行项目

来源：`bom_child`。

| seed 字段 | 建议归档位置 | 说明 |
| --- | --- | --- |
| `bom_code` | 关联 BOM 头 | 必须能找到 `bom_main.bom_code` |
| `line_no`、`component_row_id` | BOM行号/来源行ID | 作为历史追溯 |
| `child_code_normalized` / `child_code` | 物料编码 | 优先用标准化编码关联 `material_items.material_code` |
| `child_name` | 物料名称快照 | 与库存物料互校验 |
| `quantity` | 用量 | 进入 BOM 行 |
| `unit`、`unit_raw`、`unit_cn`、`unit_es` | 单位与多语言单位 | `unit` 为系统使用值 |
| `target_process_code`、`target_process_name` | BOM行目标工序 | 关联工艺路线节点 |
| `target_route_code`、`target_route_node_code` | 目标路线/节点 | 归档到 BOM-工序映射 |
| `mapping_status`、`matched_rule_code`、`mapping_confidence` | 映射质量 | 导入预览或数据质量字段 |
| `mapping_confirmed_at/by`、`source_row_no` | 确认与来源 | 历史追溯 |

### 7.2 BOM与工序映射

来源：`mes_bom_process_mapping`、`mes_material_mapping_rule`。

这部分不进入产品/SKU主档，应作为 SKU/BOM 生产资料沉淀。

| seed 字段 | 建议归档位置 | 说明 |
| --- | --- | --- |
| `bom_code`、`material_code` | BOM行匹配键 | 定位哪个BOM物料进入哪个工序 |
| `process_code`、`process_name` | 工序快照 | 与工序库对齐 |
| `target_route_code`、`target_route_node_code` | 路线节点 | 关联产品路线或SKU路线实例 |
| `mapping_rule`、`matched_rule_code`、`mapping_confidence` | 规则与置信度 | 预览阶段显示，低置信度需人工确认 |
| `rule_code`、`rule_name`、`priority` | 物料映射规则 | 规则主档，不写SKU字段 |
| `product_code`、`sku_code`、`bom_code` | 规则适用范围 | 判断产品级规则、SKU级规则或BOM级规则 |
| `condition_json` | 复杂条件 | 保留 JSON，不拆字段 |

## 8. 工艺路线字段归档

来源：`master_route_seed.process_routes`、`rule_config_seed.operation_templates`、`task_split_rules`。

| seed 字段 | 建议归档位置 | 层级 |
| --- | --- | --- |
| `route_code` | 工艺路线编码 | 产品层路线模板 |
| `route_name` | 工艺路线名称 | 产品层路线模板 |
| `product_code` | 归属产品 | 产品层 |
| `version`、`status`、`effective_date` | 路线版本状态 | 产品层路线模板 |
| `is_default`、`priority`、`condition_json` | 默认路线与适用条件 | 产品层路线选择规则 |
| `nodes[].operation_code` | 工序编码 | 工序库引用 |
| `nodes[].step_no`、`step_name` | 工序顺序与名称 | 路线节点 |
| `nodes[].config_json.inputDimensions` | 输入维度 | SKU生成/生产计划 |
| `nodes[].config_json.outputDimensions` | 输出维度 | SKU/半成品生成 |
| `nodes[].config_json.outputBaseCode` | 输出基础码 | 半成品/成品编码 |
| `nodes[].config_json.outputType` | 输出类型 | `semi_finished` 或 `finished` |
| `nodes[].config_json.outputColorCode` | 固定输出颜色 | SKU颜色派生 |
| `edges[].from_node_code/to_node_code` | 节点依赖关系 | 路线边 |

拆分规则重点：

| `task_split_rules.split_dimensions` | 归档判断 |
| --- | --- |
| `product_code` | 产品级任务或产品级半成品 |
| `product_code + phone_model` | 产品+机型层，属于SKU生成前的型号维度 |
| `color` | 颜色维度，通常要落到SKU层生产任务 |
| `phone_model + color` | 明确SKU维度 |

## 9. 字典与基础资料前置关系

SKU归档前必须先能解析以下字典，否则只能进入待匹配池：

| 字典 | 主键 | 被哪些字段引用 |
| --- | --- | --- |
| 品牌字典 `mes_brand_code` | `brand_code` | `mes_sku_master.phone_brand`、`mes_phone_model_code.brand_code` |
| 手机型号字典 `mes_phone_model_code` | `model_code` | `mes_sku_master.model_code`、路线维度 `phone_model_code` |
| 颜色字典 `mes_color_code` | `color_code` | `mes_sku_master.color_code`、`mes_product_item_color.color_code`、BOM颜色 |
| 物料字典 `material_items` | `material_code` | `bom_child.child_code_normalized`、物料映射规则 |
| 工序字典 `operation_templates` | `operation_code` | 路线节点、BOM工序映射、产能和报工规则 |

## 10. 暂不进入产品/SKU主档的字段

以下字段有业务价值，但不建议直接放入产品或SKU主档：

| 字段/对象 | 暂存位置 | 原因 |
| --- | --- | --- |
| `mes_resource`、`mes_machine` | 设备/资源中心 | 属于排产资源，不是产品/SKU属性 |
| `mes_resource_capability`、`mes_machine_capacity` | 资源能力/产能规则 | 会随设备和班次变化，不能固定到SKU主档 |
| `mes_shift`、`mes_team` | 组织排班资料 | 生产执行维度 |
| `report_templates.fields_json` | 报工模板 | 表单配置，应独立版本化 |
| `material_rules` | 领料规则 | 与仓库、工序、缺料策略相关 |
| `capacity_rules`、`changeover_rules` | 产能/换型规则 | 工艺排产配置 |
| `mapping_confidence`、`mapping_source` | 导入预览/数据质量 | 用于判断可信度，不是业务主属性 |

## 11. 建议的落地顺序

本次不导入，但后续真正落地时建议按以下顺序：

1. 先沉淀字典：品牌、手机型号、颜色、工序、物料。
2. 再沉淀产品层：`mes_product` + 产品别名 + 产品路线模板。
3. 再沉淀 SKU层：`mes_sku_master`，用 `article_code/sku_code` 作为主识别键，关联产品、机型、颜色。
4. 再沉淀 SKU 的 BOM：`bom_main` + `bom_child`。
5. 再沉淀 SKU 的生产资料：BOM工序映射、路线节点、拆分规则、报工模板、领料规则、产能规则。
6. 最后处理资源排产：设备、机台、能力、班次、班组。

## 12. 校验规则建议

| 场景 | 处理建议 |
| --- | --- |
| `mes_sku_master.product_code` 找不到产品层 | SKU进入待匹配，不自动创建孤立SKU |
| `model_code` 找不到手机型号字典 | SKU可暂存，但标记机型字典缺失 |
| `color_code` 找不到颜色字典 | SKU可暂存，但标记颜色字典缺失 |
| 同一 `article_code` 对应多个产品 | 冲突，禁止自动归档 |
| 同一 `product_code + model_code + color_code` 对应多个 `article_code` | 冲突，需确认是否多包装/多客户版本 |
| `bom_code` 找不到 `bom_main` | SKU保留，但BOM状态标为缺失 |
| BOM行物料找不到 `material_items` | BOM行进入异常明细，不影响SKU主档 |
| 路线节点 `operation_code` 找不到工序模板 | 路线进入待确认，不影响产品主档 |

## 13. 本次结论

本批 seeds 可以先沉淀为“产品层 + SKU层 + SKU生产资料”三段：

- 产品层以 7 条 `mes_product` / `master_route_seed.products` 为主，补别名、产品路线模板和产品工序状态基础码。
- SKU层以 3830 条 `mes_sku_master` 为主，核心字段是 `article_code/sku_code + product_code + model_code + color_code + bom_code`。
- `bom_main` 的 24 条父项适合做 SKU/BOM版本承接，不建议直接当成产品线。
- `bom_child` 的 313 条明细和 311 条 BOM工序映射应归入 SKU 的 BOM与工艺资料，而不是产品/SKU主档字段。
- 规则、资源、产能、班次班组先保持独立资料，后续由产品路线或SKU生产任务引用。
