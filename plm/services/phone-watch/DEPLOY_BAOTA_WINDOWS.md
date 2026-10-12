# Windows 宝塔部署说明

目标：在 Windows 服务器的宝塔环境中，每天定时采集带新品标签的手机型号，保存到数据库，电商部门通过网页查看、修改状态和导出 CSV。

## 1. 项目目录

建议放到：

```text
C:\wwwroot\phone-watch
```

进入目录：

```powershell
cd C:\wwwroot\phone-watch
```

## 2. 安装依赖

确认 Python：

```powershell
python --version
```

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

服务器 PostgreSQL 驱动使用 `pg8000`，`requirements.txt` 已包含它，Windows 宝塔不需要编译 `psycopg2`。

## 3. 数据库选择

本地预览可继续用 SQLite：

```powershell
python -m phone_watch init-db --db data\phones.sqlite
```

如果要用 PostgreSQL，设置 Windows 环境变量，或在启动脚本前设置：

```bat
set PHONE_WATCH_DB_BACKEND=postgres
set PHONE_WATCH_PG_DRIVER=pg8000
set PHONE_WATCH_PG_HOST=127.0.0.1
set PHONE_WATCH_PG_DATABASE=phone_scraper
set PHONE_WATCH_PG_USER=postgres
set PHONE_WATCH_PG_PASSWORD=你的数据库密码
set PHONE_WATCH_PG_PORT=5432
set PHONE_WATCH_PG_OPTIONS=-c client_encoding=utf8
set PHONE_WATCH_PG_CONNECT_TIMEOUT=10
python -m phone_watch check-db
python -m phone_watch init-db
```

注意：不要把真实数据库密码提交到代码仓库。

## 4. 手动采集一次

SQLite：

```powershell
scripts\daily_collect.bat
```

该脚本会：

1. 创建锁文件，避免重复采集。
2. 运行 `python -m phone_watch collect --retention-months 5`。
3. 只清洗本次 `run_id` 抓到的数据，并增量更新到数据库。
4. 只保留带新品标签/预约/发布会/敬请期待等线索的手机型号。
5. 已开模数据永久保留；未开模、待开模、忽略数据超过 5 个月自动清理。
5. 生成候选机型。
6. 补全图片。
7. 导出 `data\phone_watch.html`。
8. 写日志到 `logs\daily_collect.log`。

## 5. 启动网页服务

前台运行，适合测试：

```powershell
scripts\run_server_windows.bat
```

后台运行：

```powershell
scripts\start_server_windows_background.bat
```

访问：

```text
http://服务器IP:8000
```

本机测试：

```text
http://127.0.0.1:8000
```

健康检查：

```powershell
scripts\check_service_windows.bat
```

## 6. Windows 宝塔计划任务

在宝塔面板中添加计划任务。

如果宝塔支持执行 bat，任务命令写：

```bat
cd /d C:\wwwroot\phone-watch && scripts\daily_collect.bat
```

如果宝塔只支持 Shell/命令执行，可写：

```bat
cmd /c "cd /d C:\wwwroot\phone-watch && scripts\daily_collect.bat"
```

建议每天早上执行一次，例如 08:00。

## 7. 长期运行网页服务

Windows 上建议二选一：

1. 用宝塔自带进程守护，如果你的 Windows 宝塔面板支持。
2. 用 Windows 任务计划程序，设置“开机时启动”，执行：

```bat
cmd /c "cd /d C:\wwwroot\phone-watch && scripts\run_server_windows.bat"
```

## 8. 反向代理

如果要用域名访问，例如：

```text
https://phone-watch.example.com
```

宝塔站点反向代理到：

```text
http://127.0.0.1:8000
```

然后配置 SSL。

## 9. 页面功能

- 候选机型：国内/韩国有、墨西哥没有的型号。
- 全部机型：本次采集到且带新品标签的手机型号。
- 状态：未处理、待打样、已打样、忽略。
- 支持单条修改、批量修改。
- 支持导出当前页 CSV。

CSV 接口：

```text
/export/phones.csv
/export/candidates.csv
```

## 10. 关键日志

```text
logs\daily_collect.log
logs\server.log
```

也可以直接执行脚本查看最近日志和错误：

```bat
cd /d C:\wwwroot\phone-watch && scripts\view_baota_logs.bat
```

默认显示最近 120 行；如果想看最近 300 行：

```bat
cd /d C:\wwwroot\phone-watch && scripts\view_baota_logs.bat 300
```
