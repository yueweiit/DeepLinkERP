# 2026-08-03 PLM 已归档产品 SKU、BOM、工艺路线按产品归档目标效果沉淀

## 1. 问题说明

当前数据库里的原产品线没有丢失，7 个已归档产品线仍然存在：

| 产品编码 | 产品名称 | 当前产品层级 |
| --- | --- | --- |
| `NBA4030` | 亮甲Rainbow 2.0 | `product_line` |
| `NBD4030` | 圣殿Case Blindaje | `product_line` |
| `NDN4030` | Alterna幻甲 | `product_line` |
| `NFA4020` | 幻影Fantasía Case | `product_line` |
| `NFB4020` | titanio 骑士2.0 | `product_line` |
| `NHA4030` | 超队Súper Capitán | `product_line` |
| `NWV4030` | waves薇武士 | `product_line` |

现在看起来像“原来的产品没有了”，核心原因是展示口径不对：SKU 也存放在 `plm_product`，并且本次导入了 3830 条 `model_variant`。如果已归档页面直接平铺查询 `archived` 产品，而不是先显示产品线、再把 SKU 挂到产品线下面，产品卡片会被 SKU 行淹没。

## 2. 目标效果

已归档模块第一层必须是“产品”，不是 SKU。

目标结构：

```text
已归档
├─ 产品：NBA4030 亮甲Rainbow 2.0
│  ├─ SKU：按 NBA4030 前缀归档
│  ├─ BOM：按 BOM-NBA4030 前缀归档
│  └─ 工艺路线：亮甲 2.0 的 4 条标准路线
├─ 产品：NBD4030 圣殿Case Blindaje
│  ├─ SKU：按 NBD4030 前缀归档
│  ├─ BOM：按 BOM-NBD4030 前缀归档
│  └─ 工艺路线：圣殿标准路线
└─ ...
```

页面上应该看到 7 个产品入口。进入某个产品后，再看到该产品下的 SKU、BOM、工艺路线。

## 3. 归档识别规则

### 3.1 产品层

产品层只取：

```sql
plm_product.product_type = 'product_line'
and plm_product.status = 'archived'
```

目标产品编码为 `NBA4030/NBD4030/NDN4030/NFA4020/NFB4020/NHA4030/NWV4030`。

### 3.2 SKU 层

SKU 不应该在已归档首页平铺成产品。SKU 应挂在产品线下面。

优先归档规则：

| 优先级 | 规则 | 说明 |
| ---: | --- | --- |
| 1 | `sku.parent_product_id = product_line.product_id` | 最稳定，当前导入已写入 |
| 2 | `left(sku.finished_product_code, 7) = product_line.product_code` | 兼容已有关联缺失的数据 |
| 3 | `left(sku.product_code, 7) = product_line.product_code` | `product_code=article_code` 时可用 |
| 4 | `sku.import_short_code` 前缀匹配 | 兜底 |

SKU 层展示字段建议：

| 字段 | 来源 |
| --- | --- |
| SKU 编码 | `finished_product_code`，兜底 `product_code` |
| 手机型号 | `model` / `phone_model_code` |
| 颜色 | `color` / `color_code` |
| 外部短码 | `import_short_code` |
| 状态 | `status` |

### 3.3 BOM 层

BOM 也不应该脱离产品线展示。

优先归档规则：

| 优先级 | 规则 | 说明 |
| ---: | --- | --- |
| 1 | `plm_product_bom.product_id = product_line.product_id` | 当前参考 BOM 已这样写入 |
| 2 | `bom_code like 'BOM-' || product_code || '%'` | 兼容历史 BOM 前缀 |
| 3 | `output_inventory_code/erp_bom_reference` 前缀匹配 | 兜底 |

当前导入的 BOM 是 `candidate/seed_reference`，目标展示要标为“参考 BOM/颜色关系”，不能显示成已发布正式 BOM。

### 3.4 工艺路线层

工艺路线按产品线归档。

优先归档规则：

| 优先级 | 规则 | 说明 |
| ---: | --- | --- |
| 1 | `plm_process.product_id = product_line.product_id` 且 `process_type='routing'` | 当前标准路线已这样写入 |
| 2 | `process_param_json.productCode = product_line.product_code` | 兼容路线 JSON |
| 3 | 路线编码与产品映射表 | 兜底，例如 `ROUTE-WAVESHELL-V1 -> NWV4030` |

历史自动修复路线如 `ROUTE-NBA4030-IMPORT-14` 可以保留，但在目标效果里应标记为“历史自动修复路线/辅助路线”，不要盖过 seed 标准路线。

## 4. 目标产品与 SKU、BOM 统计

| 产品 | SKU 数 | SKU 色码 | BOM 数 |
| --- | ---: | --- | ---: |
| `NBA4030` 亮甲Rainbow 2.0 | 628 | `01,02,07,12,31,40,43,64,66` | 6 |
| `NBD4030` 圣殿Case Blindaje | 218 | `02,43` | 1 |
| `NDN4030` Alterna幻甲 | 36 | `31,40` | 1 |
| `NFA4020` 幻影Fantasía Case | 1609 | `02,04,07,08,13,43` | 4 |
| `NFB4020` titanio 骑士2.0 | 90 | `02,07,08,13,43` | 4 |
| `NHA4030` 超队Súper Capitán | 1068 | `02,07,08,13` | 4 |
| `NWV4030` waves薇武士 | 181 | `02,12,17,43,56,64,86` | 4 |

说明：SKU 色码来自 `mes_sku_master.color_short_code`，BOM 颜色来自 `bom_main.custom_bom_specification` 映射后的颜色字典。SKU 色码和 BOM 色码不完全相同是源数据差异，不应在页面上强行合并。

## 5. 产品关联工艺路线

### `NBA4030` 亮甲Rainbow 2.0

目标展示 4 条标准路线：

| 路线编码 | 路线名称 | 节点 |
| --- | --- | --- |
| `ROUTE-RAINBOW-DYE-NO-UV-V1` | 亮甲 2.0 染色-无UV打印 | 注塑 PC 部件 `NBA1020` -> 注塑 TPU 部件 `NBA1010` -> PC 染色 `NBA3020` -> 组装和打包 `NBA4030` |
| `ROUTE-RAINBOW-DYE-UV-V1` | 亮甲 2.0 染色-带UV打印 | 注塑 PC 部件 `NBA1020` -> 注塑 TPU 部件 `NBA1010` -> PC 染色 `NBA3020` -> TPU 打印 `NBA2030` -> 组装和打包 `NBA4030` |
| `ROUTE-RAINBOW-INJECTION-CLEAR-V1` | 亮甲 2.0 透明款-无UV打印 | 注塑 PC 部件 `NBA1020` -> 注塑 TPU 部件 `NBA1010` -> 组装和打包 `NBA4030` |
| `ROUTE-RAINBOW-INJECTION-CLEAR-UV-V1` | 亮甲 2.0 透明款-带UV打印 | 注塑 PC 部件 `NBA1020` -> 注塑 TPU 部件 `NBA1010` -> TPU 打印 `NBA2030` -> 组装和打包 `NBA4030` |

颜色路线目标：透明 `31` 优先走透明款路线；`01/02/07/12/66` 走染色路线。

### `NBD4030` 圣殿Case Blindaje

| 路线编码 | 路线名称 | 节点 |
| --- | --- | --- |
| `ROUTE-BLINDAJE-V1` | 圣殿标准路线 | 注塑 TPU 部件 `NBD1010` -> 注塑 ABS 背板 `NBD1020` -> ABS 夹子配件 `NBD1022` -> 注塑 PC 前盖 `NBD1021` -> 组装和打包 `NBD4030` |

目标颜色：`02` 黑色。

### `NDN4030` Alterna幻甲

| 路线编码 | 路线名称 | 节点 |
| --- | --- | --- |
| `ROUTE-ALTERNA-V1` | 幻甲标准路线 | 注塑 PC 部件 `NDN1020` -> 注塑 TPU 部件 `NDN1010` -> PC 片打印 `NDN2030` -> 组装和打包 `NDN4030` |

目标颜色：`31` 透明。

### `NFA4020` 幻影Fantasía Case

| 路线编码 | 路线名称 | 节点 |
| --- | --- | --- |
| `ROUTE-FANTASY-V1` | 骑士 1.0 标准路线 | 注塑 PC 部件 `NFA1020` 固定白色 `04` -> 注塑 TPU 部件 `NFA1010` 固定黑色 `02` -> PC 喷油 `NFA3020` 随 SKU 颜色 -> 组装和打包 `NFA4020` |

目标 BOM 颜色：`02/07/08/13`。  
注意：SKU 中存在 `04` 白色，但路线里白色更像 PC 部件固定色，不应默认当作正式 BOM 成品色。

### `NFB4020` titanio 骑士2.0

| 路线编码 | 路线名称 | 节点 |
| --- | --- | --- |
| `ROUTE-TITANIO-V1` | 骑士 2.0 标准路线 | 注塑 PC 部件 `NFB1020` 固定白色 `04` -> 注塑 TPU 部件 `NFB1010` 固定黑色 `02` -> PC 喷油 `NFB3020` 随 SKU 颜色 -> 组装和打包 `NFB4020` |

目标 BOM 颜色：`02/07/08/13`。  
注意：工序颜色直接映射里 `NFB4020` 不完整，目标页面可以展示 BOM/SKU 颜色，但工序颜色要标记“待补齐直接映射”。

### `NHA4030` 超队Súper Capitán

| 路线编码 | 路线名称 | 节点 |
| --- | --- | --- |
| `ROUTE-SUPER-CAPITAN-V1` | 超队标准路线 | 注塑 PC 部件 `NHA1020` 固定白色 `04` -> 注塑 TPU 部件 `NHA1010` 固定黑色 `02` -> 注塑 TPU 垫圈 `NHA00001` -> 注塑 PP 垫圈 `NHA00002` -> PC 喷油 `NHA3020` 随 SKU 颜色 -> 组装和打包 `NHA4030` |

目标 BOM 颜色：`02/07/08/13`。  
注意：白色 `04` 是 PC 部件固定色，不应自动归为成品 SKU/BOM 颜色。

### `NWV4030` waves薇武士

| 路线编码 | 路线名称 | 节点 |
| --- | --- | --- |
| `ROUTE-WAVESHELL-V1` | 薇武士标准路线 | 注塑 TPU `NWV1010` 随 SKU 颜色 -> 打孔 `NWV1010` 随 SKU 颜色 -> 组装和打包 `NWV4030` |

目标 BOM 颜色：`02/12/48/86`。  
SKU 色码中存在 `17/56/64` 等销售色码；`BOM-NWV4030000048-001` 是 `ROSA NEON - FIUCSIA`，当前按 BOM 字典 `48 Neon Pink` 展示，不应强行等同为 SKU 的 `17 Fucsia`。

## 6. 页面目标

已归档首页：

| 区域 | 目标 |
| --- | --- |
| 顶部统计 | 显示 7 个产品线、3830 个 SKU、24 个参考 BOM、10 条标准路线 |
| 产品列表 | 只显示 `product_line` 产品卡片/行，不直接平铺 SKU |
| 产品行信息 | 产品编码、产品名称、SKU 数、SKU 颜色数、BOM 数、路线数 |
| 点击产品 | 进入产品归档详情 |

产品归档详情：

| Tab | 展示 |
| --- | --- |
| SKU | 当前产品前缀下的 SKU，可按手机型号、颜色筛选 |
| BOM | 当前产品前缀下的参考 BOM，展示颜色、版本、关联路线 |
| 工艺路线 | 当前产品的标准路线；历史自动修复路线折叠到“历史/辅助路线” |
| 工序颜色 | 当前产品基础码与颜色关系，固定部件色和成品色分开展示 |

## 7. 后续落地建议

1. 已归档产品首页查询条件固定为 `product_type=product_line`。
2. SKU 管理页改为“先产品后 SKU”，通过 `parent_product_id` 和前缀兜底聚合。
3. BOM 管理页改为“先产品后 BOM”，通过 `product_bom.product_id` 和 `BOM-产品编码` 前缀兜底聚合。
4. 工艺路线页改为“先产品后路线”，标准 seed 路线优先展示，`ROUTE-*-IMPORT-14` 标为历史辅助路线。
5. 对本次导入的 `seed_reference` BOM 保持草稿/参考态，补齐物料明细和成本后才能发布为正式 BOM。

## 8. 结论

目标效果不是把 3830 个 SKU 当作 3830 个已归档产品，而是把 7 个原产品作为归档主入口。SKU、BOM、工艺路线都要围绕产品前缀和父产品关系归档展示。
