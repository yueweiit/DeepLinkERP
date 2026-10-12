# 2026-07-27 PLM ECOUNT 新物料编码总表导入规则代码实现沉淀

## 1. 背景

本次实现基于以下文档和约束：

- `D:\work\资料\PLM\docs\文件沉淀\开发提示词.md`
- `docs\文件沉淀\2026-07-27-PLM-ECOUNT新物料编码总表导入规则与物料组分类沉淀.md`
- PLM 七大核心对象边界：本次只增强 `Inventory` 主数据导入，不新增 `Material`、`MaterialGroup` 等根对象，不实现 ECOUNT/ERP 正式集成。

目标是让 `01 ECOUNT 新物料编码总表.xlsx/csv` 可以直接进入库存主数据导入预览，不再因为原表多行表头报 `模板缺少必填列：inventory_code`，并处理源表没有供应商、状态、币种等 PLM 必填字段的问题。

## 2. 修改文件

| 文件 | 修改内容 |
| --- | --- |
| `plm-server/src/main/java/com/yuewei/plm/module/importexport/service/impl/MasterDataImportExportServiceImpl.java` | 增加 ECOUNT 表头识别、复合表头映射、CSV 读取、库存字段默认值、单位标准化、物料组派生、ECOUNT 元数据备注沉淀。 |
| `plm-server/src/test/java/com/yuewei/plm/module/importexport/service/impl/MasterDataImportExportServiceImplTest.java` | 增加 ECOUNT 原始工作簿预览测试，覆盖复合表头、默认供应商、单位标准化、分类派生、重复新物料编码。 |
| `plm-web/src/api/modules/importExport.ts` | 将导入预览行状态类型扩展为 `ready | error | warning`，为后续预警级别兼容做准备。 |

## 3. 核心代码与逻辑

### 3.1 读取入口按文件类型分流

```java
private List<RowData> readRows(MultipartFile file, String objectType) {
    String fileName = file.getOriginalFilename() == null ? "" : file.getOriginalFilename().toLowerCase(Locale.ROOT);
    if (fileName.endsWith(".csv")) return readCsvRows(file, objectType);
    return readExcelRows(file, objectType);
}
```

说明：

- `.csv` 进入文本解析。
- 其他文件继续走 Apache POI，当前仍以 `.xlsx` 为主要支持对象。
- Excel 导入时如果是 `inventory`，优先读取 sheet `物料编码表`。

### 3.2 识别 ECOUNT 多行复合表头

实现点：

- 扫描前 5 行，查找同时包含 `新物料编码`、`物料名称` 的行。
- 找到后把该行视为主表头，下一行视为子表头。
- 对 `一级`、`二级` 这类父表头，组合成 `一级.大类编码`、`一级.名称`、`二级.流水编码`、`二级.名称`。
- 如果表头后下一行不像数据，则跳过 ECOUNT 源表第 4 行的辅助状态文字，从第 5 行开始读真实物料。

核心映射：

```java
registerHeaderAliases(aliases, "inventory_code", "新物料编码", "物料编码", "库存编码", "编码", "物料/模具编码");
registerHeaderAliases(aliases, "unit", "基本单位", "单位", "库存单位", "计量单位");
registerHeaderAliases(aliases, "ecount_major_code", "一级.大类编码", "一级大类编码", "大类编码");
registerHeaderAliases(aliases, "ecount_major_name", "一级.名称", "一级名称", "一级.名　称", "大类名称");
registerHeaderAliases(aliases, "ecount_minor_code", "二级.流水编码", "二级流水编码", "流水编码");
registerHeaderAliases(aliases, "ecount_minor_name", "二级.名称", "二级名称", "二级.名　称");
registerHeaderAliases(aliases, "legacy_inventory_code", "旧编码");
registerHeaderAliases(aliases, "barcode", "条形码", "条码");
registerHeaderAliases(aliases, "source_created_date", "新增日期");
```

### 3.3 Inventory 必填列兼容

原 PLM 模板要求 `inventory_type`、`status` 必填；ECOUNT 源表没有这些列。本次兼容规则：

- `status` 表头缺失时允许通过，行值默认 `available`。
- `inventory_type` 表头缺失时，如果存在 ECOUNT 一级分类字段，则允许通过，并从一级分类派生。
- `unit` 仍按行级必填校验，空单位会进入错误队列，不静默补默认单位。

### 3.4 行值标准化与默认值

```java
values.put("unit", normalizeInventoryUnit(values.get("unit")));
values.put("barcode", normalizeBlankToken(values.get("barcode")));
if (!StringUtils.hasText(values.get("inventory_type"))) values.put("inventory_type", deriveInventoryType(values));
if (!StringUtils.hasText(values.get("status"))) values.put("status", "available");
if (!StringUtils.hasText(values.get("currency_code"))) values.put("currency_code", "CNY");
if (!StringUtils.hasText(values.get("supplier_name"))) values.put("supplier_name", DEFAULT_SUPPLIER_NAME);
values.put("remark", appendEcountRemark(values));
```

规则说明：

- `个 PIEZA`、`套 PIEZA`、`KG` 等混合单位会标准化为 PLM 当前可读单位。
- `#N/A`、`N/A`、`NA` 条码视为空。
- 源表没有供应商时统一为 `默认供应商`，解决无供应商无法导入的问题。
- 源表没有币种时默认 `CNY`。
- Excel 日期单元格读取为 `yyyy-MM-dd`，避免进入备注时变成 Excel 日期序列号。

### 3.5 物料组到 `inventory_type` 的短期派生

当前不扩展库存类型枚举，先按文档沉淀的粗粒度规则派生：

| ECOUNT 一级分类 | 当前派生 |
| --- | --- |
| `YL 原料`、`GL 钢料/铜料` | `material` |
| `FL/KGFL/NHA/NAR/0 辅料` | `packaging` |
| `GJ/HE/WJ/MJ/KGMJ/SB/KGSB` 以及工具、模具、模架、模芯、设备 | `tooling` |
| `JG 加工`、`RC 日常工作`、`WX 费用` | `unsupported`，预览时报错并要求人工确认 |

说明：这是当前 Inventory 枚举能力下的兼容方案。ECOUNT 原始一二级分类不会丢失，会追加到 `remark`。

### 3.6 ECOUNT 元数据沉淀到备注

当前不新增数据库字段，因此把历史追溯信息写入 `remark`：

```text
ECOUNT导入：一级=YL/原料，二级=000001/原料TPU，旧编码=YL000001，新增日期=2020/2/13
```

导入提交时原有 `appendHistoryRemark` 仍会追加 `历史存档导入`，便于和普通人工创建记录区分。

## 4. 好处

- 用户可以直接上传 ECOUNT 原始 `物料编码表`，不需要手工改成 PLM 模板列名。
- 解决源表无供应商导致导入失败的问题，统一落到 `默认供应商`。
- 保留 ECOUNT 一二级分类、旧编码、条码、新增日期，后续追溯和清洗不丢历史信息。
- 文件内重复 `新物料编码` 会在预览阶段明确报错，避免导入时静默覆盖主键语义。
- 当前不扩表、不新增根对象，符合 PLM 项目边界，便于先完成历史主数据迁移。

## 5. 后续维护建议

1. 后续建议给 Inventory 增加独立字段：`ecount_major_code`、`ecount_major_name`、`ecount_minor_code`、`ecount_minor_name`、`legacy_inventory_code`、`barcode`、`source_created_date`、`source_system`，避免长期把结构化数据压入 `remark`。
2. 建议扩展 `inventory_type` 枚举，至少补充 `auxiliary`、`mold`、`equipment`、`service`，减少把 ECOUNT 物料组压缩成 `packaging/tooling` 的信息损失。
3. 预览结果建议后续真正区分 `error` 与 `warning`：重复编码、缺必填仍阻断；编码规则不一致、历史分类冲突、条码重复可以作为 warning。
4. 首批历史导入前建议先对 ECOUNT 源表做重复编码清理报告，尤其是文档中已识别的 128 个重复新物料编码。
5. 如果 CSV 来自 WPS/Excel 导出，建议确认编码统一为 UTF-8；如后续发现 GBK CSV，可在 `readCsvRows` 增加编码探测或用户选择。

## 6. 验证结果

已执行：

```powershell
plm-server\.codex_tmp\apache-maven-3.9.9\bin\mvn.cmd -f plm-server\pom.xml -Dtest=MasterDataImportExportServiceImplTest test
```

结果：未进入 Maven 编译/测试阶段，本机缺少 Java 环境。

```text
The JAVA_HOME environment variable is not defined correctly,
this environment variable is needed to run this program.
```

已执行静态空白检查：

```powershell
git diff --check -- plm-server/src/main/java/com/yuewei/plm/module/importexport/service/impl/MasterDataImportExportServiceImpl.java plm-web/src/api/modules/importExport.ts
git diff --no-index --check -- NUL plm-server/src/test/java/com/yuewei/plm/module/importexport/service/impl/MasterDataImportExportServiceImplTest.java
```

结果：未发现空白错误；仅提示 Git 未来可能将 LF 转为 CRLF。

## 7. 2026-07-30 中文转换模板流水码导入修正

### 7.1 问题现象

库存中心按物料组树展示时，用户反馈物料明细显示为 `000001 继电器`、`000008 RECTIFICADORA NEUMÁTICA 风动打磨机` 等半截编码，看起来像“物料被导成物料组”。

### 7.2 根因

库存中心左侧物料组树来自 `plm_material_group`，物料本身仍落在 `plm_inventory`。真正的问题是部分中文转换模板把 ECOUNT 的二级流水码放进了 `物料编码` 列，例如：

- `物料组 = GL 金属材料`
- `物料编码 = 000008`

导入层原先按 `物料编码` 原样写入 `plm_inventory.inventory_code`，因此编码缺少一级前缀 `GL`。

### 7.3 修正策略

修改 `MasterDataImportExportServiceImpl`：

1. 当 `物料组` 形如 `GL 金属材料` 时，解析出：
   - `ecount_major_code = GL`
   - `ecount_major_name = 金属材料`
2. 当 `inventory_code` 是纯数字流水号，且存在 `ecount_major_code` 时，自动补成完整编码：
   - `000008` -> `GL000008`
3. 如果原始 `新物料编码/物料编码` 已经是完整编码，例如 `GJ000260`，则保持原值不改。

### 7.4 验证

新增测试：

- `inventoryPreviewRebuildsCodeWhenConvertedTemplateUsesSequenceCode`

执行：

```powershell
cd D:\work\Yuewei\plm-server
..\.plm-server\.codex_tmp\apache-maven-3.9.9\bin\mvn.cmd -Dtest=MasterDataImportExportServiceImplTest test
```

结果：23 个测试全部通过。

### 7.5 错误历史数据清理

新增一次性清理迁移：

- `plm-server/src/main/resources/db/migration/V20260730_1010__cleanup_numeric_inventory_import_codes.sql`

清理范围：

1. `plm_inventory.inventory_code` 为纯数字流水码，例如 `000001`、`000008`。
2. 已关联 ECOUNT 物料组，即 `material_group_id` 指向 `plm_material_group.source_system = 'ECOUNT'`。
3. 备注包含 `ECOUNT导入` 或 `历史存档导入`。

清理方式：

- 只软删除 `plm_inventory` 错误明细行：`deleted_flag = 1`。
- 不删除 `plm_material_group` 物料组字典。
- 不处理已经是完整编码的物料，例如 `GJ000260`、`GL000008`。

执行新迁移并重新导入后，中文转换模板中的 `GL + 000008` 会以 `GL000008` 写入库存物料。

### 7.6 2026-07-30 兜底清理补充

用户重建后日志显示 Flyway 只迁移到 `20260730.1000`，未看到 `20260730.1010` 的执行记录；同时 `1010` 的清理条件依赖中文备注内容，如果历史数据备注存在编码差异，可能漏清理。

本次追加高版本迁移：

- `plm-server/src/main/resources/db/migration/V20260730_1110__cleanup_numeric_inventory_import_codes_fallback.sql`

兜底范围：

- `plm_inventory.inventory_code` 为纯数字流水码，例如 `000001`、`000008`。
- `plm_inventory.material_group_id` 已关联到 `plm_material_group.source_system = 'ECOUNT'` 的物料组。
- 不再依赖 `remark` 中的中文文本，避免编码差异导致漏清。

执行效果：

- 只软删除错误库存明细：`deleted_flag = 1`。
- 在 `remark` 追加 `cleanup_numeric_inventory_import_codes_fallback_20260730` 作为清理标记。
- 不删除 `plm_material_group` 物料组字典，也不处理 `GL000008`、`GJ000260` 这类已经完整的物料编码。

重建后确认日志应出现：

```text
Migrating schema "plm" to version "20260730.1110 - cleanup numeric inventory import codes fallback"
```

然后重新导入物料模板，`GL 金属材料 + 000008` 会由导入层补全为 `GL000008`。

### 7.7 2026-07-30 物料组与真实物料分离修正

用户截图显示 `000568 冰盾片材` 出现在库存中心的物料组级联选择器中，但右侧物料列表仍为 0。这说明早期 ECOUNT 物料组字典把二级流水码/物料名作为 `group_level = 2` 的物料组节点展示了，界面上看起来仍然没有把“真正的物料”和“物料组”分离。

本次修正口径：

- 库存中心筛选树只展示 `plm_material_group.group_level = 1` 的一级业务分类，例如 `FL 辅料`、`GL 金属材料`、`GJ 工具`。
- `000568 冰盾片材` 这类二级流水记录不再作为筛选树节点展示。
- 库存明细如果历史上挂到了二级流水节点，接口展示时折回其父级一级物料组。
- 新导入库存物料以后只关联一级物料组；ECOUNT 二级流水码和名称继续保留在 `remark`，用于历史追溯，不再作为 UI 分类层级。

涉及文件：

- `plm-server/src/main/java/com/yuewei/plm/module/inventory/service/impl/JdbcInventoryCenterService.java`
- `plm-server/src/main/java/com/yuewei/plm/module/importexport/service/impl/MasterDataImportExportServiceImpl.java`
- `plm-server/src/main/resources/db/migration/V20260730_1120__inventory_material_group_l1_scope.sql`

迁移效果：

- 将已关联到 ECOUNT 二级物料组的 `plm_inventory.material_group_id` 批量改回父级一级物料组。
- 在备注中追加 `inventory_material_group_l1_scope_20260730` 标记。
- 不删除二级字典数据，避免丢失 ECOUNT 历史追溯信息。

重建后日志应出现：

```text
Migrating schema "plm" to version "20260730.1120 - inventory material group l1 scope"
```

目标效果：物料组选择器只剩真实分类；真实物料在右侧库存列表中展示，筛选 `FL 辅料` 时展示归属该分类的物料明细。

### 7.8 2026-07-30 ECOUNT 末级组全量转库存物料

进一步核对 `D:\work\资料\PLM\工作簿1.xlsx` 后确认：截图红框中的 `000568 冰盾片材` 不是个例。早期 `plm_material_group` 字典中的大量 `group_level = 2` 记录来自 ECOUNT `物料编码表` 的“二级流水编码 + 名称”，业务含义是物料明细，不是物料组。

本次补充全量修复：

- 新增迁移 `plm-server/src/main/resources/db/migration/V20260730_1130__seed_inventory_from_ecount_workbook_and_archive_minor_groups.sql`。
- 从 `工作簿1.xlsx` 的 `物料编码表` 生成库存物料种子数据，写入 `plm_inventory`。
- 可导入库存物料 7,984 行；`JG/RC/WX` 这类加工、日常工作、费用口径暂不自动落 Inventory。
- 源表存在 128 个重复编码，迁移按 `inventory_code + source_row_no` 取首条，并通过 `on conflict (inventory_code) do nothing` 避免与已存在物料冲突。
- 将 ECOUNT `group_level = 2` 的末级“伪物料组”归档软删除，避免继续出现在物料组选择器。
- 将 `ecount_major_code = 0` 且名称为 `辅料` 的异常口径归一为 `FL/辅料`。
- 纯数字异常编码优先用 `一级前缀 + 二级流水编码` 补全，例如：
  - 源表：`0 / 辅料 / 000568 / 冰盾片材 / inventory_code=0000568`
  - 入库：`FL000568 / 冰盾片材`

同步修改导入层：

- `normalizeInventoryMajorAlias`：统一 `0/辅料 -> FL/辅料`。
- `normalizeInventoryCode`：当源 `inventory_code` 是纯数字时，优先使用 `ecount_minor_code` 作为流水码补完整编码。

验证点：

- `FL000568 冰盾片材` 会作为 `plm_inventory` 物料出现。
- `000568 冰盾片材` 不再作为物料组节点出现。
- 物料组树只保留一级分类，如 `FL 辅料`、`GJ 工具`、`GL 金属材料`。
