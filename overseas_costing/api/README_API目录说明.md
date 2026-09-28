# API 目录说明

适用目录：`overseas_costing/api`

## 文件清单

| 文件 | 中文名 | 用途 |
| --- | --- | --- |
| `batch.py` | 批次查询接口 | 批次列表、批次详情、明细分页、版本列表、钉钉原单跳转 |
| `workbench.py` | 工作台只读接口 | 工作台队列与汇总（只读） |
| `calculate.py` | 编辑重算接口 | 编辑字段、批量编辑、重算、版本切换、成本试算确认 |
| `edit_session.py` | 批次编辑租约接口 | 抢/续/放批次编辑锁，返回写令牌（`edit_token` + `modified`） |
| `category.py` | 商品品类归类接口 | 返回商品品类归类预览，后续接 AI 分类与人工确认 |
| `materials.py` | 物料表接口 | 物料表格与发货数量来源的最小权限接口 |
| `material_fee_workspace.py` | 物料费用工作台接口 | 快照读写与缓存刷新（`refresh_snapshot` / `check_freshness` / `get_snapshot`） |
| `fees.py` | 费用与凭证接口 | 费用与凭证工作台的最小权限接口 |
| `import_api.py` | 导入接口 | 导入 Excel / OA 数据、上传附件、完税凭证 PDF 预览解析、解析快照保存与记录摘要查询 |
| `packing_api.py` | 装箱与运费接口 | 装箱来源、缓存刷新、不可变确认和独立运费试算 |
| `logistics_settlement.py` | 物流结算接口 | 月结结算 RPC：服务端持有源数据、乐观修订号、按批次鉴权 |
| `air_sea_comparison.py` | 空海运对比接口 | 独立空/海运成本对比记录的读写 |
| `profit.py` | 利润测算接口 | 利润测算 |
| `review.py` | 成本复核接口 | 成本复核整改沟通 |
| `usage.py` | 使用记录接口 | 工作台使用记录 |
| `writeback.py` | 回写接口 | 检查回写条件、执行回写、分站点计划预览/保存/执行、账本读取、核对并重试单条 ERP 同步请求 |

## 当前约定

1. API 层只做参数入口和结果封装
2. 核心业务放到 `services/`
3. 需要 whitelisted 的方法统一从这里暴露
4. 写接口一律要求 `edit_token` + `expected_modified`（见 `services/edit_session_service.py`）；
   只读接口命名以 `get_` / `list_` / `preview_` / `check_` 开头，前端据此判断断网重试是否安全
