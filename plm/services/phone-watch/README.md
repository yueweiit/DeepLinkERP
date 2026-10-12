# 手机上新监控工具

用于定期采集墨西哥、中国、韩国三星以及全球参考来源的新款手机信息，并辅助判断“其他地区已出现但墨西哥未出现”的候选机型，服务手机壳开模评估、送审和状态维护。

## 当前数据库口径

生产和日常运行推荐使用 PostgreSQL。程序仍保留 SQLite 兼容能力，方便本地临时测试。

默认推荐后端：

```text
PHONE_WATCH_DB_BACKEND=postgres
PHONE_WATCH_PG_DRIVER=pg8000
PHONE_WATCH_PG_HOST=127.0.0.1
PHONE_WATCH_PG_DATABASE=phone_scraper
PHONE_WATCH_PG_USER=postgres
PHONE_WATCH_PG_PORT=5432
```

数据库密码必须通过环境变量提供，不要写入代码或文档：

```powershell
$env:PHONE_WATCH_PG_PASSWORD="实际密码"
```

Web 页面、采集、手动添加型号、状态维护、Tipo 开模状态、字段管理都会通过 `phone_watch/db.py` 统一连接当前数据库后端。切到 PG 后，网页会直接展示 PG 中已有的 `phones`、`candidates`、`molding_tipo_records` 等表数据。

## 功能

- 配置化采集 Motorola、OPPO、vivo、HONOR、Xiaomi、ZTE、Samsung。
- 采集字段：手机型号、图片、价格、发布时间、上市日期、发布链接、来源国家。
- 清洗并识别手机型号，过滤非手机记录。
- 对比来源国家和墨西哥数据，生成候选机型。
- Web 页面支持国家、品牌、型号、状态、标签、价格筛选。
- 支持手动添加型号、字段管理、Tipo 类型管理。
- 支持开模状态维护：`未开模`、`部分开模`、`已开模`、`忽略`。
- 支持钉钉审批同步和 Tipo 明细状态展示。
- 支持来源业务分表和开模记录表同步。

## PG 模式快速启动

先设置 PG 密码：

```powershell
$env:PHONE_WATCH_PG_PASSWORD="实际密码"
```

初始化或补齐 PG 表结构：

```powershell
py -m phone_watch init-db
```

检查 PG 连接：

```powershell
py -m phone_watch check-db
```

启动服务版网页：

```powershell
py -m phone_watch serve --host 0.0.0.0 --port 8000
```

打开浏览器访问：

```text
http://127.0.0.1:8000
```

Windows 生产启动脚本：

```powershell
.\scripts\run_server_windows.bat
```

Windows 后台启动脚本：

```powershell
.\scripts\start_server_windows_background.bat
```

## 生产采集

Windows 定时采集脚本默认使用 PostgreSQL：

```powershell
.\scripts\daily_collect.bat
```

手动执行采集：

```powershell
py -m phone_watch collect --max-pages 6 --timeout 20 --retention-months 5
```

`collect` 会增量更新数据库：`已开模` 数据长期保留，`未开模`、`部分开模`、`忽略` 数据按保留期清理。

## SQLite 本地 fallback

如需临时使用本地 SQLite，可显式设置后端并传入 `--db`：

```powershell
$env:PHONE_WATCH_DB_BACKEND="sqlite"
py -m phone_watch init-db --db data\phones.sqlite
py -m phone_watch pipeline --db data\phones.sqlite --config config\sources.json --max-pages 2
py -m phone_watch serve --db data\phones.sqlite --port 8000
```

注意：`--db` 只在 SQLite 后端有效。PG 模式下连接信息来自 `PHONE_WATCH_PG_*` 环境变量。

## 业务分表

系统会从主表同步来源分表和开模记录表：

```text
phones_mx
phones_cn
phones_kr_samsung
phones_global
molding_records
```

手动同步命令：

```powershell
py -m phone_watch sync-business-tables
```

## 常用验证命令

```powershell
py -m phone_watch check-db
py -m phone_watch init-db
py -m phone_watch sync-business-tables
py -m phone_watch sync-dingtalk --dry-run --limit 1
```

如果页面显示“暂无数据”，先访问 API 判断是数据库真的没有数据，还是连接/SQL 报错：

```text
http://127.0.0.1:8000/api/summary
http://127.0.0.1:8000/api/phones
http://127.0.0.1:8000/api/candidates
```

## 维护注意

- 不要把 PG 密码、钉钉密钥写入仓库文件。
- 新增字段或表结构时必须同时考虑 SQLite 和 PostgreSQL。
- Web 页面不要直接连接数据库，统一走 `webapp.py` 的 API 和 `db.py` 的查询函数。
- 主开模状态使用 `部分开模`；`待开模` 只用于 Tipo 明细状态。
- 生产数据库禁止执行清表、删库、覆盖式导入等破坏性操作。
