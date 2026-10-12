# Docker 一键完整环境部署

本文档用于 Windows Docker Desktop 和 Linux/宝塔服务器部署。当前 Docker 结构已重构为完整栈：

- `phone-watch`：手机新品监控 Web 服务。
- `postgres`：项目本地 PostgreSQL 数据库。
- `phone_watch_pg_data`：PostgreSQL 持久化数据卷。
- `./data`：静态导出、SQLite fallback 数据等本地文件。
- `./logs`：采集和服务日志。

---

## 1. 文件说明

项目根目录包含：

```text
Dockerfile
.dockerignore
docker-compose.yml
.env.example
```

职责：

- `Dockerfile`：构建 Python 3.11 运行环境，安装项目依赖和 Playwright Chromium。
- `.dockerignore`：排除真实密钥、本地日志、SQLite 数据库、缓存文件。
- `docker-compose.yml`：一键启动 Web + PostgreSQL。
- `.env.example`：本地 Docker 默认配置模板，不包含真实生产密钥。

---

## 2. 快速启动

进入项目目录：

```powershell
cd C:\Users\JT\Desktop\备份\cst\phone_watch\python-sqlite-https-www-motorola-com
```

复制环境变量模板：

```powershell
copy .env.example .env
```

首次启动完整环境：

```powershell
docker compose up -d --build
```

初始化或补齐数据库表结构：

```powershell
docker compose run --rm phone-watch python -m phone_watch init-db
```

检查数据库连接：

```powershell
docker compose run --rm phone-watch python -m phone_watch check-db
```

访问页面：

```text
http://127.0.0.1:8000
```

---

## 3. 默认数据库配置

默认 `.env.example` 适配 Compose 内部 PostgreSQL：

```text
PHONE_WATCH_DB_BACKEND=postgres
PHONE_WATCH_PG_DRIVER=pg8000
PHONE_WATCH_APP_PG_HOST=postgres
PHONE_WATCH_APP_PG_DATABASE=phone_scraper
PHONE_WATCH_APP_PG_USER=postgres
PHONE_WATCH_APP_PG_PASSWORD=phone_watch_dev_password
PHONE_WATCH_APP_PG_PORT=5432
POSTGRES_PORT=5432
```

说明：

- `PHONE_WATCH_APP_PG_HOST=postgres` 是 Compose 内部服务名，不是公网地址。
- `PHONE_WATCH_APP_PG_*` 会在容器内映射为程序实际读取的 `PHONE_WATCH_PG_*`。
- `POSTGRES_PORT=5432` 是宿主机访问容器 PG 的端口。
- 本地开发默认密码是占位值，生产部署必须修改。
- 不要把真实数据库密码、钉钉密钥写入代码或文档。

---

## 4. 常用命令

查看容器：

```powershell
docker compose ps
```

查看 Web 日志：

```powershell
docker compose logs -f phone-watch
```

查看 PostgreSQL 日志：

```powershell
docker compose logs -f postgres
```

重启 Web：

```powershell
docker compose restart phone-watch
```

停止完整环境：

```powershell
docker compose down
```

停止并重新构建：

```powershell
docker compose down
docker compose up -d --build
```

注意：`docker compose down` 不会删除 `phone_watch_pg_data` 数据卷。不要随意执行带 `-v` 的 down 命令，除非确认要删除数据库数据。

---

## 5. 采集和维护命令

手动采集一次：

```powershell
docker compose run --rm phone-watch python -m phone_watch collect --max-pages 6 --timeout 20 --retention-months 5 --export-out data/phone_watch.html
```

小范围采集验证：

```powershell
docker compose run --rm phone-watch python -m phone_watch crawl --country MX --brand SAMSUNG --max-pages 1 --timeout 20
```

同步业务分表：

```powershell
docker compose run --rm phone-watch python -m phone_watch sync-business-tables
```

导出静态 HTML：

```powershell
docker compose run --rm phone-watch python -m phone_watch export-html --out data/phone_watch.html
```

钉钉 dry-run：

```powershell
docker compose run --rm phone-watch python -m phone_watch sync-dingtalk --dry-run --limit 10
```

---

## 6. Linux/宝塔部署

服务器目录示例：

```bash
mkdir -p /www/wwwroot/phone-watch
cd /www/wwwroot/phone-watch
```

上传项目代码后，确认包含：

```text
Dockerfile
.dockerignore
docker-compose.yml
phone_watch/
config/
scripts/
requirements.txt
.env.example
```

准备环境变量：

```bash
cp .env.example .env
nano .env
```

生产部署至少要修改：

```text
PHONE_WATCH_PG_PASSWORD=你的强密码
DINGTALK_TOKEN_APP_KEY=你的钉钉配置
DINGTALK_TOKEN_APP_SECRET=你的钉钉配置
DINGTALK_AGENT_ID=你的钉钉配置
DINGTALK_PROCESS_CODE=你的钉钉配置
DINGTALK_ORIGINATOR_USER_ID=你的钉钉配置
```

启动：

```bash
docker compose up -d --build
docker compose run --rm phone-watch python -m phone_watch init-db
docker compose run --rm phone-watch python -m phone_watch check-db
```

访问：

```text
http://服务器IP:8000
```

---

## 7. 使用外部 PostgreSQL

如果生产已有外部 PostgreSQL，可以在 `.env` 中覆盖：

```text
PHONE_WATCH_APP_PG_HOST=你的外部数据库地址
PHONE_WATCH_APP_PG_DATABASE=phone_scraper
PHONE_WATCH_APP_PG_USER=postgres
PHONE_WATCH_APP_PG_PASSWORD=你的真实密码
PHONE_WATCH_APP_PG_PORT=5432
```

这种模式下：

- `phone-watch` 会连接外部 PG。
- Compose 里的 `postgres` 服务仍会创建，但业务不会使用它。
- 如需完全不启动内置 PG，后续可以再拆 `docker-compose.external-pg.yml` 覆盖文件。

---

## 8. 定时采集建议

宝塔计划任务或 crontab 可执行：

```bash
cd /www/wwwroot/phone-watch
mkdir -p logs
docker compose run --rm phone-watch python -m phone_watch collect --max-pages 6 --timeout 20 --retention-months 5 --export-out data/phone_watch.html >> logs/docker_daily_collect.log 2>&1
```

建议每天早上运行一次。

---

## 9. 验证命令

修改 Docker 配置后先执行：

```powershell
docker compose config
```

然后按顺序验证：

```powershell
docker compose up -d --build
docker compose run --rm phone-watch python -m phone_watch init-db
docker compose run --rm phone-watch python -m phone_watch check-db
```

如果页面显示“暂无数据”，先访问 API 判断是数据库无数据还是接口报错：

```text
http://127.0.0.1:8000/api/summary
http://127.0.0.1:8000/api/phones
http://127.0.0.1:8000/api/candidates
```

---

## 10. 维护注意

- 不要提交 `.env`、`.env.baota` 或真实密钥。
- 不要执行 `docker compose down -v`，除非确认要删除 PostgreSQL 数据卷。
- `data/` 和 `logs/` 挂载到宿主机，容器删除后仍保留。
- 首次构建会较慢，因为需要安装 Playwright Chromium。
- 如果端口 8000 被占用，修改 `.env` 中 `PORT=8015`，访问 `http://127.0.0.1:8015`。
- 如果宿主机 5432 已被占用，修改 `.env` 中 `POSTGRES_PORT=15432`，容器内部连接仍使用 `PHONE_WATCH_PG_PORT=5432`。

---

## 11. 新闻采集与静态导出

### 独立 Playwright 新闻脚本

生产环境推荐使用宝塔宿主机上的 `scripts/ithome_playwright_today.py --import-db` 作为新闻计划任务，因为它可以稳定复用同一个 IT之家登录 profile。新闻脚本只抓当天新闻；网页新闻模块默认展示数据库中仍在 7 天保留期内的已有新闻，按发布时间或采集时间倒序。

如果必须在 Docker 容器内运行独立脚本，需要把 Playwright 用户数据目录挂载为持久 volume，否则登录态会随容器重建丢失。示例：

```bash
docker compose run --rm phone-watch python scripts/ithome_playwright_today.py \
  --timeout 60 \
  --user-data-dir /app/data/ithome-playwright-profile \
  --import-db \
  --out data/ithome_playwright_today.json
```

首次登录也必须使用同一个 `--user-data-dir`：

```bash
docker compose run --rm phone-watch python scripts/ithome_playwright_today.py \
  --user-data-dir /app/data/ithome-playwright-profile \
  --login-wait-seconds 180
```

每日脚本现在会先执行手机型号主采集，再尽力执行新闻采集：

```bash
python -m phone_watch collect --max-pages 6 --timeout 20 --retention-months 5 --export-out data/phone_watch.html
python -m phone_watch collect-news --timeout 20
```

执行原则：

- 不替换现有 `collect` 主流程。
- `collect` 失败时脚本仍按失败退出，避免隐藏主采集问题。
- `collect-news` 失败只写入日志，不阻断当天手机型号采集结果。
- 静态 HTML 导出会携带 `news.items`，离线页面仍可展示新闻板块已有数据。
- `ithome_brand_search` 与 `ithome_phone_today` 是两个独立来源，不能用手机频道文章池替代品牌 Tag/搜索来源。

Docker 手动验证：

```powershell
docker compose config
docker compose run --rm phone-watch python -m phone_watch collect-news --timeout 20
docker compose run --rm phone-watch python -m phone_watch export-html --out data/phone_watch.html
```

IT之家来源分开验证：

```powershell
docker compose run --rm phone-watch python -m phone_watch collect-news --source-type ithome_phone_today --timeout 20 --render-mode never
docker compose run --rm phone-watch python -m phone_watch collect-news --brand XIAOMI --source-type ithome_brand_search --timeout 20 --render-mode always
docker compose run --rm phone-watch python -m phone_watch collect-news --brand SAMSUNG --source-type ithome_brand_search --timeout 20 --render-mode always
```

维护注意：

- `ithome_brand_search` 优先使用 IT之家品牌 Tag 页，建议 `source_name=IT之家品牌 Tag`、`render=true`，解析优先选择 `ul.bl a.title`。
- Tag 页、搜索页和手机频道首页只作为入口，入库和静态导出的 URL 必须是文章详情链接。
- 如果 Tag 页或搜索入口不可用，日志应保留对应品牌来源失败原因；手机频道当天新闻可继续采集。
