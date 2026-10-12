# PLM ECOUNT 物料组与库存中心测试方法沉淀

日期：2026-07-27

## 一、测试目标

本次测试覆盖刚完成的三段闭环：

1. ECOUNT 新物料编码总表可稳定转换为 `plm_material_group` 物料组迁移脚本。
2. Inventory 导入时能按 ECOUNT 一级/二级物料组规则写入 `plm_inventory.material_group_id`。
3. 库存中心页面不再展示旧的前端硬编码物料组，而是通过后端接口读取数据库中的物料组树。

## 二、后端测试方法

### 1. 物料组生成脚本测试

测试文件：

`tests/scripts/test_generate_ecount_material_groups.py`

测试方法：

`test_build_groups_preserves_conflicting_major_names_and_links_minor_parent`

验证点：

- 同一个一级编码存在多个历史名称时不合并错误数据。
- 二级物料组能正确挂到对应一级物料组下面。
- `MJ`、`GL` 等同编码不同名称的历史记录保留原始编码和名称。

测试方法：

`test_generate_sql_contains_table_indexes_and_seed_counts`

验证点：

- 生成的 SQL 包含 `plm_material_group` 建表语句。
- 包含唯一索引、父子索引和 `plm_inventory.material_group_id` 扩展。
- 生成结果包含一级组、二级组和种子数量统计。

执行命令：

```powershell
python tests\scripts\test_generate_ecount_material_groups.py -v
```

本次执行结果：

```text
Ran 2 tests
OK
```

### 2. 物料组迁移生成验证

脚本文件：

`scripts/generate_ecount_material_groups.py`

执行命令：

```powershell
python scripts\generate_ecount_material_groups.py
```

本次执行结果：

```text
source=D:\work\资料\PLM\01 ECOUNT 新物料编码总表.csv
rows=7987
level1=23
level2=7810
output=D:\work\Yuewei\plm-server\src\main\resources\db\migration\V20260727_1300__ecount_material_groups.sql
```

说明：

- 有效物料记录：7987 条。
- 一级物料组：23 个。
- 二级物料组：7810 个。
- 输出迁移文件：`V20260727_1300__ecount_material_groups.sql`。

### 3. 库存中心后端快照测试

测试文件：

`plm-server/src/test/java/com/yuewei/plm/module/inventory/service/impl/JdbcInventoryCenterServiceTest.java`

测试方法：

`snapshotReturnsMaterialGroupTreeAndInventoryRowsFromDatabase`

验证点：

- `JdbcInventoryCenterService.snapshot()` 返回根节点 `all`。
- 根节点下面能返回数据库中的 ECOUNT 物料组树。
- 一级节点格式为 `material-group:{material_group_id}`。
- 库存行能按 `material_group_id` 生成相同格式的 `nodeId`。
- 前端可直接通过 `nodeId` 过滤，不再按物料名称猜分类。

测试方法：

`snapshotFallsBackToAllGroupWhenMaterialGroupTableIsMissing`

验证点：

- 当 `plm_material_group` 表不存在时，接口不会报错。
- 返回树保留根节点 `all`。
- 子节点为空，库存中心仍可加载基础库存列表。

### 4. 导入库存关联物料组测试

测试文件：

`plm-server/src/test/java/com/yuewei/plm/module/importexport/service/impl/MasterDataImportExportServiceImplTest.java`

测试方法：

`inventoryImportLinksEcountMaterialGroupWhenDictionaryExists`

验证点：

- ECOUNT 导入行包含一级编码/名称和二级编码/名称时，优先生成二级物料组 key。
- 二级 key 格式：

```text
L2:{ecount_major_code}:{ecount_major_name}:{ecount_minor_code}:{ecount_minor_name}
```

- 测试样例期望 key：

```text
L2:YL:原料:000001:原料TPU
```

- 查到 `plm_material_group.material_group_id` 后，插入 `plm_inventory` 时写入 `material_group_id`。

兼容规则：

- 如果只有一级编码/名称，则使用一级 key：

```text
L1:{ecount_major_code}:{ecount_major_name}
```

- 如果字典表不存在、字段不存在或查不到组，不阻断导入，只是不写 `material_group_id`。

后端 Maven 验证状态：

```powershell
plm-server\.codex_tmp\apache-maven-3.9.9\bin\mvn.cmd -f plm-server\pom.xml '-Dtest=JdbcInventoryCenterServiceTest,MasterDataImportExportServiceImplTest' test
```

本次环境未能执行，原因：

```text
The JAVA_HOME environment variable is not defined correctly
```

结论：

- 后端测试方法已补齐。
- 当前机器需要先配置 `JAVA_HOME` 后才能运行 Maven 单测。

## 三、前端测试方法

### 1. 库存中心 API 接入测试

测试文件：

`plm-web/src/api/modules/__tests__/inventory-center-api.spec.ts`

测试方法：

`uses Inventory center snapshot endpoint instead of frontend mock data`

验证点：

- `getInventoryCenterSnapshot()` 不再返回前端假数据。
- 实际请求接口：

```text
/inventories/center-snapshot
```

- 返回数据结构包含：

```text
tree: InventoryTreeNode[]
items: InventoryListRow[]
```

### 2. 前端假数据清理回归测试

测试文件：

`plm-web/src/api/modules/__tests__/no-runtime-mock-data.spec.ts`

调整点：

- 库存中心已经接入真实后端接口，因此从 `notConnected` 负向测试清单移除。
- 其他仍未接真实接口的模块继续保持负向测试，防止运行时误展示前端假数据。

执行命令：

```powershell
cd plm-web
npm run test:run -- src/api/modules/__tests__/inventory-center-api.spec.ts src/api/modules/__tests__/no-runtime-mock-data.spec.ts
```

本次执行结果：

```text
Test Files  2 passed
Tests       15 passed
```

### 3. 前端类型检查

执行命令：

```powershell
cd plm-web
npm run type-check
```

本次执行结果：

```text
vue-tsc --noEmit
exit code 0
```

验证点：

- `InventoryTreeNode` 与库存中心页面树转换逻辑类型正确。
- `InventoryListRow.status` 已兼容后端可能返回的 `draft`、`closed` 状态。
- 库存中心页面用 `serverItemGroupOptions` 作为 Cascader 数据源，接口返回什么物料组，页面展示什么物料组。

## 四、手工验收方法

### 1. 数据库迁移验收

启动后端并执行 Flyway 后，检查：

```sql
select count(*) from plm_material_group where deleted_flag = 0 and group_level = 1;
select count(*) from plm_material_group where deleted_flag = 0 and group_level = 2;
select column_name from information_schema.columns where table_name = 'plm_inventory' and column_name = 'material_group_id';
```

期望：

- 一级物料组数量约 23。
- 二级物料组数量约 7810。
- `plm_inventory.material_group_id` 字段存在。

### 2. 导入后关联验收

导入 ECOUNT 物料编码表后检查：

```sql
select inventory_code, inventory_name, material_group_id
from plm_inventory
where deleted_flag = 0
  and material_group_id is not null
limit 20;
```

期望：

- ECOUNT 导入的物料有 `material_group_id`。
- 二级编码和名称完整的行优先关联到二级物料组。

### 3. 库存中心页面验收

打开库存中心页面，检查：

1. 物料组下拉树不再显示旧硬编码分组，如 `PC`、`MHC 超星 3.0` 等固定前端数据。
2. 页面物料组来自 `GET /api/v1/inventories/center-snapshot`。
3. 点击一级物料组时，可以看到其下二级组物料。
4. 点击二级物料组时，只显示该二级组关联物料。

## 五、结论

本次完成的测试覆盖了生成、导入、后端查询和前端接入四个关键点。当前自动验证通过的部分包括 Python 生成脚本测试、前端 API 测试和前端类型检查。后端 Java 单测已补齐，但当前机器缺少 `JAVA_HOME`，需要配置 JDK 后执行 Maven 验证。
