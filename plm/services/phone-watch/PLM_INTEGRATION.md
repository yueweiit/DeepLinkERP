# Phone Watch 与 PLM 集成

## 本地启动

1. 从 `.env.example` 复制一份 `.env.local`，填写本地数据库密码、随机服务令牌以及已校验 dump 的绝对路径。
2. 启动内部服务：

   ```bash
   docker compose --env-file services/phone-watch/.env.local up -d --build phone-watch-db phone-watch phone-watch-worker
   ```

3. 将同一个令牌通过 `APP_PHONE_WATCH_TOKEN` 提供给 PLM Server，并设置 `APP_PHONE_WATCH_ENABLED=true`。

本地数据库使用 PostgreSQL 17，以匹配生产导出的 custom-format archive 版本。`phone-watch` 没有宿主机端口，只能由 Compose 内部网络访问。旧 `/api/*` 与独立网页入口默认关闭，钉钉写操作也默认关闭。

## 运行边界

- `PHONE_WATCH_LOCAL_ONLY=true` 会拒绝连接非回环、非 Compose 的数据库主机。
- 采集 worker 使用 `Asia/Shanghai` 时区，每日 08:00 依次执行手机和新闻采集。
- PLM 是唯一浏览器入口；Python `/internal/v1` 只接受服务令牌。
- `.env.local`、dump、日志、PID、缓存和 SQLite 运行文件不得提交 Git。

## 生产灰度与回滚

生产编排定义在根目录 `docker-compose.baota.yml`。部署时先保持
`APP_PHONE_WATCH_ENABLED=false`，验证内部健康检查和数据库连通性后再逐步开启。
切流完成前不要停止旧 8010 进程，也不要关闭云安全组入口。

回滚时只需关闭 `APP_PHONE_WATCH_ENABLED` 并恢复旧服务。PLM 数据库仅新增
`plm_market_watch_link`，不会改写原协作计划记录或 Phone Watch 源数据。
