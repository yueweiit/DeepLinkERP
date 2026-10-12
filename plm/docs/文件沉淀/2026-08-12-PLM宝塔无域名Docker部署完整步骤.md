# 2026-08-12 PLM 宝塔无域名 Docker 部署完整步骤

## 1. 部署目标

将本地已清理完成的 Yuewei PLM 系统部署到宝塔服务器，内部系统先不申请域名，通过服务器 IP + 端口访问。

目标访问方式：

```text
http://服务器IP:8110
```

目标架构：

```text
浏览器
  -> http://服务器IP:8110
  -> plm-web(Nginx)
  -> /api 反向代理到 plm-server
  -> 远程 PostgreSQL：8.135.19.108:5432/plm_yuewei?currentSchema=plm
  -> Docker 内部 Redis
```

## 2. 当前已确认信息

### 2.1 远程 PostgreSQL

```text
数据库地址：8.135.19.108
端口：5432
数据库名：plm_yuewei
Schema：plm
用户名：postgres
密码：CHANGE_ME_PRIVATELY
```

必须在后端连接串中带上 `currentSchema=plm`：

```env
DB_URL=jdbc:postgresql://8.135.19.108:5432/plm_yuewei?currentSchema=plm
DB_USERNAME=postgres
DB_PASSWORD=CHANGE_ME_PRIVATELY
```

### 2.2 数据导入校验结果

远程数据库已导入本地清理后的数据，核心数据量：

```text
product    3883
bom        64
process    359
attachment 46
order      9
```

产品状态分布：

```text
model_variant / archived 3830
product_line  / archived 4
product_line  / released 7
```

说明：工作台进行中产品已清理，当前远程库可作为宝塔部署目标库。

## 3. 端口放行

### 3.1 必须放行

```text
宝塔面板端口：用于登录宝塔
8110：PLM 前端访问端口
```

### 3.2 不建议公网放行

```text
8080：后端接口端口，正常由前端 Nginx 内部代理，不给用户直连
5432：PostgreSQL，只允许宝塔服务器 IP 和维护电脑 IP 访问
6379：Redis，不允许公网访问
```

### 3.3 无域名阶段说明

当前不申请域名，不配置 SSL，不需要开放 `80` 和 `443`。

后续如果申请域名，再改为：

```text
80/443 -> 宝塔 Nginx 反向代理 -> 127.0.0.1:8110
```

## 4. 上传项目

建议服务器目录：

```bash
/www/wwwroot/yuewei-plm
```

上传本地项目根目录：

```text
D:\work\Yuewei
```

上传到服务器后目录结构应类似：

```text
/www/wwwroot/yuewei-plm/docker-compose.yml
/www/wwwroot/yuewei-plm/plm-server
/www/wwwroot/yuewei-plm/plm-web
/www/wwwroot/yuewei-plm/plm-database
/www/wwwroot/yuewei-plm/docs
```

不建议上传：

```text
.git
.codex_tmp
node_modules
target
dist
```

如果已上传这些目录，不影响运行，但会增加传输体积。

## 5. 部署前必须调整 Docker Compose

当前 `docker-compose.yml` 中后端数据库连接写死为 Docker 内部 PostgreSQL：

```yaml
DB_URL: jdbc:postgresql://postgres:5432/plm
DB_USERNAME: plm
DB_PASSWORD: ${DB_PASSWORD:-plm123}
```

宝塔部署要连接远程 PostgreSQL，应调整为从 `.env` 读取：

```yaml
DB_URL: ${DB_URL:-jdbc:postgresql://postgres:5432/plm}
DB_USERNAME: ${DB_USERNAME:-plm}
DB_PASSWORD: ${DB_PASSWORD:-plm123}
```

同时建议生产部署不启动内部 `postgres` 服务，避免误连本地容器库。可选两种方式：

### 方案 A：保留 postgres 服务，但后端明确连远程库

适合快速部署。只要 `DB_URL` 指向远程库，后端不会使用内部 PostgreSQL。

注意：这种方式会额外启动一个无用的 `plm-postgres` 容器。

### 方案 B：新增生产 Compose 文件，不启动 postgres

推荐正式使用。新增 `docker-compose.baota.yml`，只保留 `redis`、`server`、`web`，后端连接远程 PostgreSQL。

示例：

```yaml
services:
  redis:
    image: redis:7-alpine
    container_name: plm-redis
    command: redis-server --appendonly yes
    volumes:
      - plm_redisdata:/data
    restart: unless-stopped
    networks:
      - plm-net

  server:
    build:
      context: ./plm-server
      dockerfile: Dockerfile
      args:
        BUILD_IMAGE: ${SERVER_BUILD_IMAGE:-maven:3.9-eclipse-temurin-17}
        RUNTIME_IMAGE: ${SERVER_RUNTIME_IMAGE:-eclipse-temurin:17-jre}
    container_name: plm-server
    environment:
      SPRING_PROFILES_ACTIVE: prod
      SERVER_PORT: "8080"
      DB_URL: ${DB_URL}
      DB_USERNAME: ${DB_USERNAME}
      DB_PASSWORD: ${DB_PASSWORD}
      REDIS_HOST: redis
      REDIS_PORT: "6379"
      APP_SECURITY_ENABLED: "${APP_SECURITY_ENABLED:-true}"
      APP_SECURITY_DEV_TOKEN: "${APP_SECURITY_DEV_TOKEN:-dev-token}"
      APP_STORAGE_LOCAL_ROOT: data/uploads
      DINGTALK_MODEL_VARIANT_PROCESS_CODE: "${DINGTALK_MODEL_VARIANT_PROCESS_CODE:-PROC-BD65F530-F66F-46B9-8F72-0567DD68F60C}"
      DINGTALK_APP_KEY: "${DINGTALK_APP_KEY:-}"
      DINGTALK_APP_SECRET: "${DINGTALK_APP_SECRET:-}"
      DINGTALK_CALLBACK_TOKEN: "${DINGTALK_CALLBACK_TOKEN:-}"
      DINGTALK_AUTO_APPROVER_USER_ID: "${DINGTALK_AUTO_APPROVER_USER_ID:-}"
      DINGTALK_PRODUCT_LINE_CC_USER_IDS: "${DINGTALK_PRODUCT_LINE_CC_USER_IDS:-}"
      DINGTALK_OUTBOUND_ENDPOINT: "${DINGTALK_OUTBOUND_ENDPOINT:-}"
    ports:
      - "${SERVER_PORT:-8080}:8080"
    volumes:
      - plm_uploads:/app/data/uploads
    depends_on:
      - redis
    restart: unless-stopped
    networks:
      - plm-net

  web:
    build:
      context: ./plm-web
      dockerfile: Dockerfile
    container_name: plm-web
    ports:
      - "${WEB_PORT:-8110}:80"
    depends_on:
      - server
    restart: unless-stopped
    networks:
      - plm-net

networks:
  plm-net:
    driver: bridge

volumes:
  plm_redisdata:
  plm_uploads:
```

## 6. 创建 .env

在服务器项目根目录创建：

```bash
/www/wwwroot/yuewei-plm/.env
```

本仓库已提供宝塔环境模板：

```text
.env.baota.example
```

上传项目后可先复制一份：

```bash
cp .env.baota.example .env
```

然后修改 `.env` 中的 `APP_SECURITY_DEV_TOKEN`、钉钉配置和 `DINGTALK_OUTBOUND_ENDPOINT` 里的服务器 IP。

内容：

```env
WEB_PORT=8110
SERVER_PORT=8080

DB_URL=jdbc:postgresql://8.135.19.108:5432/plm_yuewei?currentSchema=plm
DB_USERNAME=postgres
DB_PASSWORD=CHANGE_ME_PRIVATELY

APP_SECURITY_ENABLED=true
APP_SECURITY_DEV_TOKEN=请替换为随机长字符串

DINGTALK_MODEL_VARIANT_PROCESS_CODE=PROC-BD65F530-F66F-46B9-8F72-0567DD68F60C
DINGTALK_APP_KEY=请填写正式钉钉应用Key
DINGTALK_APP_SECRET=请填写正式钉钉应用Secret
DINGTALK_CALLBACK_TOKEN=请填写正式回调Token
DINGTALK_AUTO_APPROVER_USER_ID=请填写代同意人员UserId
DINGTALK_PRODUCT_LINE_CC_USER_IDS=请填写抄送人员UserId，多个用英文逗号
DINGTALK_OUTBOUND_ENDPOINT=http://服务器IP:8110/api/v1/integrations/dingtalk/outbound
```

内部系统无域名时，钉钉回调地址使用：

```text
http://服务器IP:8110/api/v1/integrations/dingtalk/...
```

如果钉钉要求公网可访问，必须确认 `8110` 端口已从公网访问到宝塔服务器。

## 7. 安装 Docker

在宝塔面板中优先使用 Docker 管理器安装 Docker 和 Docker Compose。

安装完成后，在宝塔终端执行：

```bash
docker version
docker compose version
```

能看到版本号即安装成功。

## 8. 构建并启动

进入项目目录：

```bash
cd /www/wwwroot/yuewei-plm
```

如果采用方案 A：

```bash
docker compose up -d --build
```

如果采用方案 B：

```bash
docker compose -f docker-compose.baota.yml up -d --build
```

查看容器状态：

```bash
docker compose ps
```

或：

```bash
docker ps
```

期望看到：

```text
plm-web      Up
plm-server   Up
plm-redis    Up
```

如果采用方案 A，还会看到：

```text
plm-postgres Up
```

## 9. 启动后验证

### 9.1 查看后端日志

方案 A：

```bash
docker compose logs -f server
```

方案 B：

```bash
docker compose -f docker-compose.baota.yml logs -f server
```

重点确认没有数据库连接失败：

```text
Connection refused
password authentication failed
relation xxx does not exist
schema xxx does not exist
```

### 9.2 服务器本机访问前端

```bash
curl -I http://127.0.0.1:8110
```

期望返回：

```text
HTTP/1.1 200 OK
```

### 9.3 服务器本机访问后端

如果后端暴露了 8080：

```bash
curl http://127.0.0.1:8080/api/v1/health
```

如果没有健康检查接口，可通过前端页面登录和接口请求验证。

### 9.4 浏览器访问

在本机浏览器打开：

```text
http://服务器IP:8110
```

登录账号：

```text
engineer01 / plm123456
engineer02 / plm123456
```

### 9.5 页面验证清单

至少验证以下页面：

```text
登录页可打开
工作台可打开
项目归档可打开
产品管理可打开
SKU/型号颜色数据可打开
BOM 管理可打开
工艺路线可打开
资料中心可打开
```

重点确认：

```text
页面没有 404
接口没有 500
工作台没有残留进行中测试产品
产品、BOM、工艺、资料数据能正常查询
```

## 10. 远程数据库验证命令

在任意装有 Docker 的机器执行：

```bash
docker run --rm -e PGPASSWORD=CHANGE_ME_PRIVATELY postgres:15-alpine \
  psql -h 8.135.19.108 -p 5432 -U postgres -d plm_yuewei \
  -c "select product_type, status, count(*) from plm.plm_product where deleted_flag = 0 group by product_type, status order by product_type, status;"
```

核心模块数量：

```bash
docker run --rm -e PGPASSWORD=CHANGE_ME_PRIVATELY postgres:15-alpine \
  psql -h 8.135.19.108 -p 5432 -U postgres -d plm_yuewei \
  -c "select 'product' as module, count(*) from plm.plm_product union all select 'bom', count(*) from plm.plm_product_bom union all select 'process', count(*) from plm.plm_process union all select 'attachment', count(*) from plm.plm_attachment union all select 'order', count(*) from plm.plm_order;"
```

建议设置数据库默认 Schema：

```bash
docker run --rm -e PGPASSWORD=CHANGE_ME_PRIVATELY postgres:15-alpine \
  psql -h 8.135.19.108 -p 5432 -U postgres -d plm_yuewei \
  -c "alter database plm_yuewei set search_path to plm, public;"
```

## 11. 常见问题

### 11.1 Docker 拉镜像失败

现象：

```text
failed to resolve source metadata
registry-1.docker.io timeout
```

处理：

```bash
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'EOF'
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io"
  ]
}
EOF
systemctl daemon-reload
systemctl restart docker
docker info
```

然后重新执行：

```bash
docker compose up -d --build
```

### 11.2 页面能打开但接口失败

检查前端 Nginx 代理：

```text
plm-web/nginx.conf
```

当前配置：

```nginx
location /api/ {
    proxy_pass http://plm-server:8080;
}
```

确认 `plm-server` 容器名没有变化，且前后端在同一个 Docker network。

### 11.3 后端提示找不到表

典型错误：

```text
relation "plm_product" does not exist
```

原因：远程数据在 `plm` schema 下，连接没有指定 schema。

处理：确认 `.env`：

```env
DB_URL=jdbc:postgresql://8.135.19.108:5432/plm_yuewei?currentSchema=plm
```

### 11.4 8110 访问不了

检查：

```bash
docker ps
curl -I http://127.0.0.1:8110
```

如果服务器本机可以访问，但外部浏览器不行，检查：

```text
云服务器安全组是否放行 8110
宝塔防火墙是否放行 8110
服务器系统防火墙是否放行 8110
```

### 11.5 数据库连接失败

检查 `.env`：

```env
DB_URL=jdbc:postgresql://8.135.19.108:5432/plm_yuewei?currentSchema=plm
DB_USERNAME=postgres
DB_PASSWORD=CHANGE_ME_PRIVATELY
```

检查远程 PostgreSQL 是否允许宝塔服务器 IP 访问 `5432`。

不建议对所有公网开放 `5432`，应只允许维护电脑 IP 和宝塔服务器 IP。

## 12. 回滚方案

### 12.1 回滚容器版本

如果只是本次构建失败：

```bash
docker compose logs server
docker compose logs web
docker compose down
```

修正配置后重新启动：

```bash
docker compose up -d --build
```

### 12.2 回滚数据库

当前远程数据库由本地清理后 dump 导入。

如果导入前已有远程备份，使用：

```bash
pg_restore -h 8.135.19.108 -p 5432 -U postgres -d plm_yuewei --clean --if-exists 备份文件.dump
```

如果没有正式数据，不需要回滚，重新 drop 并创建空库后再次导入即可。

## 13. 最终部署验收标准

部署完成后应满足：

```text
http://服务器IP:8110 可打开
登录成功
前端 /api 请求能正常返回
后端日志无数据库连接错误
远程库 plm_yuewei 数据正常读取
工作台无进行中测试产品残留
产品归档、BOM、工艺、资料页面可正常打开
钉钉代同意相关配置已进入容器环境变量
```

## 14. 本次文档结论

本次部署建议使用：

```text
无域名
单业务端口 8110
Docker 部署前后端和 Redis
后端连接远程 PostgreSQL plm_yuewei
数据库连接串固定携带 currentSchema=plm
```

本仓库已新增宝塔生产部署文件：

```text
docker-compose.baota.yml
```

上传到宝塔时必须包含该文件。部署命令固定使用：

```bash
docker compose -f docker-compose.baota.yml up -d --build
```

部署前必须确认 `docker-compose.baota.yml` 已支持从 `.env` 读取 `DB_URL`、`DB_USERNAME`、`DB_PASSWORD`，否则后端仍会连接 Docker 内部 PostgreSQL，导致宝塔环境读取不到已导入的远程数据。
