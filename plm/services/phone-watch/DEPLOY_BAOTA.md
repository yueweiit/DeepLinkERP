# 宝塔服务器部署说明

目标：每天早上定时采集带新品标签的手机型号，数据保存到 PostgreSQL，电商部门通过网页查看、筛选、修改状态和导出 CSV。

## 1. 上传项目

建议放到：

```bash
/www/wwwroot/phone-watch
```

进入目录：

```bash
cd /www/wwwroot/phone-watch
```

## 2. 安装 Python 依赖

```bash
python3 --version
python3 -m pip install -r requirements.txt
chmod +x scripts/daily_collect.sh scripts/run_server.sh
chmod +x scripts/check_service.sh
```

## 3. 配置 PostgreSQL

复制环境变量模板：

```bash
cp .env.example .env
```

编辑 `.env`：

```bash
nano .env
```

填写 PostgreSQL 配置：

```bash
PHONE_WATCH_DB_BACKEND=postgres
PHONE_WATCH_PG_HOST=127.0.0.1
PHONE_WATCH_PG_DATABASE=phone_scraper
PHONE_WATCH_PG_USER=postgres
PHONE_WATCH_PG_PASSWORD=你的数据库密码
PHONE_WATCH_PG_PORT=5432
PHONE_WATCH_PG_OPTIONS=-c client_encoding=utf8
PHONE_WATCH_PG_CONNECT_TIMEOUT=10
PORT=8000
HOST=0.0.0.0
PYTHON_BIN=python3
```

不要把 `.env` 提交到代码仓库或发给不相关人员。

## 4. 初始化 PG 表

```bash
set -a && source .env && set +a
python3 -m phone_watch check-db
python3 -m phone_watch init-db
```

这会在 PostgreSQL 中创建：

- `runs`
- `raw_items`
- `phones`
- `candidates`

## 5. 手动采集一次

```bash
bash scripts/daily_collect.sh
```

日志位置：

```text
logs/daily_collect.log
```

## 6. 启动网页服务

测试启动：

```bash
bash scripts/run_server.sh
```

默认监听：

```text
0.0.0.0:8000
```

访问：

```text
http://服务器IP:8000
```

生产建议用宝塔的 “Supervisor 管理器” 或 “进程守护管理器” 守护：

```bash
cd /www/wwwroot/phone-watch && bash scripts/run_server.sh
```

## 7. 宝塔反向代理

如果要给电商部门一个正式域名，例如：

```text
https://phone-watch.example.com
```

在宝塔新建站点，设置反向代理：

```text
目标 URL: http://127.0.0.1:8000
```

然后申请 SSL。

## 8. 定时采集

宝塔面板进入 “计划任务”，新增 Shell 脚本任务。

执行周期：每天，例如早上 08:00。

脚本内容：

```bash
cd /www/wwwroot/phone-watch && bash scripts/daily_collect.sh
```

脚本会执行：

1. 创建一次独立 `collect` 采集任务。
2. 爬取墨西哥官网、中国官网、三星韩国官网。
3. 只用本次任务的 `run_id` 清洗数据，避免混用旧批次。
4. 只保留带新品标签的手机型号。
5. 生成 “中国/韩国已上新，墨西哥未上新” 候选。
6. 补全图片。
7. 同步导出静态 HTML 备份页。

脚本带 `flock` 锁，上一轮没跑完时，新一轮不会重复并发执行。

## 9. 页面功能

- 候选机型：国内/韩国已上新、墨西哥未上新的型号。
- 全部机型：最新一次采集到、识别为手机且带新品标签的机型。
- 筛选：国家、品牌、状态。
- 状态：未处理、待打样、已打样、忽略。
- 单条修改：选择状态后点 “修改”。
- 批量修改：勾选多条后点 “批量修改”。
- 导出当前页：导出当前筛选结果 CSV。

服务版 CSV 接口：

```text
/export/phones.csv
/export/candidates.csv
```

健康检查：

```bash
bash scripts/check_service.sh
```

正常会返回 `/api/summary` 的 JSON。

## 10. 数据保存

生产数据保存在 PostgreSQL：

```text
phone_scraper
```

建议定期备份 PostgreSQL 数据库，以及服务器日志：

```text
logs/daily_collect.log
```

## 11. 注意事项

当前采集口径：

- 每次定时任务会生成一个独立 run。
- 只清洗本次 run 抓到的数据，并增量更新展示表。
- 只有官网记录带新品标签、预约、发布会、敬请期待等线索的机型会进入展示表。
- `已开模` 数据永久保留；`未开模`、`待开模`、`忽略` 数据超过 5 个月自动清理。
- 新品标签会在页面卡片中展示。
- 官网没有发布时间/上市日期时，带新品标签的记录会用采集日期补齐。
- 图片优先从官网页面、结构化数据、产品图中提取。

如果某个品牌官网把数据完全放在浏览器渲染后的接口里，后续需要为该品牌增加专用适配器或 Playwright 渲染采集。

## 12. 新闻采集与静态导出接入

### 使用独立 Playwright 新闻脚本（推荐）

新闻计划任务推荐使用独立 Playwright 脚本，复用服务器上的 IT之家登录态。采集脚本只抓当天新闻；网页新闻模块默认展示数据库中仍在 7 天保留期内的已有新闻，按发布时间或采集时间倒序。

首次登录：

```bash
cd /www/wwwroot/YUEWEI/phone-watch-step6-api-news
set -a
source .env
set +a
mkdir -p logs .codex_tmp /www/wwwroot/YUEWEI/ithome-playwright-profile
python3 scripts/ithome_playwright_today.py \
  --user-data-dir /www/wwwroot/YUEWEI/ithome-playwright-profile \
  --login-wait-seconds 180
```

每日新闻采集计划任务：

```bash
cd /www/wwwroot/YUEWEI/phone-watch-step6-api-news
set -a
source .env
set +a
mkdir -p logs .codex_tmp /www/wwwroot/YUEWEI/ithome-playwright-profile
python3 scripts/ithome_playwright_today.py \
  --timeout 60 \
  --user-data-dir /www/wwwroot/YUEWEI/ithome-playwright-profile \
  --import-db \
  --out .codex_tmp/ithome_playwright_today.json \
  2>&1 | tee -a logs/ithome_playwright_today.log
tail -n 120 logs/ithome_playwright_today.log
```

查看新闻采集日志：

```bash
tail -n 200 /www/wwwroot/YUEWEI/phone-watch-step6-api-news/logs/ithome_playwright_today.log
```

`scripts/daily_collect.sh` 现在会在手机型号主采集成功后追加执行新闻采集：

```bash
python3 -m phone_watch collect-news --timeout 20
```

运行策略：

- 主采集 `collect` 仍然是每日任务核心，失败时脚本按失败处理。
- 新闻采集 `collect-news` 只做追加采集，失败时写入 `logs/daily_collect.log`，不阻断当天手机型号主采集结果。
- 静态导出 `data/phone_watch.html` 会携带 `news.items`，用于离线查看新闻板块已有数据。
- 新闻只采集标题和文章详情链接，不采集正文，不进入 `raw_items -> phones -> candidates` 主链路。
- IT之家品牌 Tag/搜索来源和 IT之家手机频道当天新闻必须保持独立，不能把 `https://mobile.ithome.com/` 文章池当作品牌搜索结果。

宝塔手动验证：

```bash
cd /www/wwwroot/phone-watch
set -a && source .env && set +a
python3 -m phone_watch collect-news --timeout 20
python3 -m phone_watch export-html --out data/phone_watch.html
```

IT之家来源分开验证：

```bash
python3 -m phone_watch collect-news --source-type ithome_phone_today --timeout 20 --render-mode never
python3 -m phone_watch collect-news --brand XIAOMI --source-type ithome_brand_search --timeout 20 --render-mode always
python3 -m phone_watch collect-news --brand SAMSUNG --source-type ithome_brand_search --timeout 20 --render-mode always
```

维护建议：

- `ithome_brand_search` 优先使用 IT之家品牌 Tag 页，配置上建议 `source_name=IT之家品牌 Tag`、`render=true`。
- Tag 页解析优先选择 `ul.bl a.title`，入库链接必须是文章详情页。
- 如果某个品牌 Tag 页失效，应在日志中保留失败原因；不要把失败伪装成空结果。
