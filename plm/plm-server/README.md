# PLM Server

`plm-server` 是 Yuewei PLM 的后端服务。当前阶段目标是搭建最小可运行后端骨架，不实现完整业务功能，先保证启动、配置、路由、健康检查、数据库连接、日志、权限入口、统一响应、统一异常和基础参数校验这些底座能力稳定。

## 技术栈

| 类型 | 选型 |
| --- | --- |
| 语言 | Java 17 |
| 框架 | Spring Boot 3.5.0 |
| Web | Spring MVC |
| 权限入口 | Spring Security |
| 参数校验 | Spring Validation / Jakarta Validation |
| 数据访问 | MyBatis-Plus 3.5.7 |
| 数据库 | PostgreSQL |
| API 文档 | SpringDoc OpenAPI |
| 日志 | SLF4J + Logback |
| 构建 | Maven |

## 目录结构

```text
plm-server/
├─ pom.xml
├─ README.md
├─ src/main/java/com/yuewei/plm/
│  ├─ PlmApplication.java
│  ├─ common/
│  │  ├─ config/
│  │  ├─ constant/
│  │  ├─ exception/
│  │  ├─ filter/
│  │  ├─ interceptor/
│  │  ├─ security/
│  │  ├─ util/
│  │  └─ vo/
│  ├─ controller/
│  ├─ service/
│  ├─ repository/
│  ├─ module/
│  │  └─ health/
│  │     ├─ controller/
│  │     ├─ dto/
│  │     └─ vo/
│  └─ infrastructure/
│     ├─ mq/
│     ├─ sse/
│     └─ storage/
└─ src/main/resources/
   ├─ application.yml
   ├─ application-dev.yml
   ├─ application-prod.yml
   └─ db/migration/
```

## 目录作用

| 目录 | 类型 | 作用 |
| --- | --- | --- |
| `PlmApplication.java` | 框架推荐 | Spring Boot 启动入口 |
| `common/config` | 框架推荐 + 项目自定义 | Security、MVC、MyBatis、OpenAPI、项目配置属性 |
| `common/exception` | 框架推荐 + 项目自定义 | `@RestControllerAdvice` 统一异常处理 |
| `common/filter` | 框架推荐 + 项目自定义 | requestId、MDC、请求链路上下文 |
| `common/security` | 框架推荐 + 项目自定义 | 权限中间件、当前用户上下文 |
| `common/vo` | 项目自定义 | `ResponseVO`、分页响应对象 |
| `module/<module>` | 项目自定义 | 后续新增业务模块的标准目录 |
| `infrastructure` | 项目自定义 | 文件、消息、SSE、后续外部系统适配 |
| `resources/application*.yml` | 框架推荐 | Spring Boot 外部化配置 |
| `resources/db/migration` | 项目自定义 | 数据库增量脚本说明 |

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_NAME` | `plm-server` | 应用名 |
| `SPRING_PROFILES_ACTIVE` | `dev` | 当前环境 |
| `SERVER_PORT` | `8080` | 服务端口 |
| `DB_URL` | `jdbc:postgresql://localhost:5433/plm` | PostgreSQL 连接地址 |
| `DB_USERNAME` | `plm` | 数据库用户名 |
| `DB_PASSWORD` | `plm123` | 开发库密码 |
| `REDIS_HOST` | `localhost` | Redis 地址 |
| `REDIS_PORT` | `6379` | Redis 端口 |
| `REDIS_DB` | `0` | Redis DB |
| `APP_SECURITY_ENABLED` | `false` in dev | 是否启用简单 token 校验 |
| `APP_SECURITY_DEV_TOKEN` | `dev-token` | 开发阶段 token |
| `APP_STORAGE_LOCAL_ROOT` | `data/uploads` | 本地文件存储根目录 |
| `LOG_LEVEL` | `info` | 项目日志级别 |

生产环境不要依赖默认密码，必须通过环境变量注入 `DB_PASSWORD`、`APP_SECURITY_DEV_TOKEN`、`APP_STORAGE_LOCAL_ROOT`。

## 统一接口规则

所有 JSON 接口统一返回：

```json
{
  "code": 0,
  "message": "success",
  "data": {},
  "requestId": "uuid",
  "timestamp": "2026-07-02T18:00:00+08:00"
}
```

成功但无结果返回空列表或空分页。失败必须返回非 0 错误码，不能用空数组或空对象掩盖错误。

## 健康检查

当前骨架提供：

```text
GET  /api/v1/health
GET  /api/v1/health/db
POST /api/v1/health/validation-probe
```

示例：

```powershell
Invoke-RestMethod http://localhost:8080/api/v1/health
Invoke-RestMethod http://localhost:8080/api/v1/health/db
```

参数校验示例：

```powershell
$body = @{ name = "skeleton" } | ConvertTo-Json
Invoke-RestMethod `
  -Uri http://localhost:8080/api/v1/health/validation-probe `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

## 权限入口

权限统一通过 Spring Security。

开发环境默认：

```yaml
app:
  security:
    enabled: false
```

启用后，请求 `/api/v1/**` 需要携带：

```text
Authorization: Bearer dev-token
```

放行路径：

```text
/api/v1/health/**
/api/v1/auth/login
/swagger-ui.html
/swagger-ui/**
/v3/api-docs/**
```

当前只是权限中间件骨架，不包含完整登录、密码校验、用户表查询。

## 日志

请求进入系统后，`RequestContextFilter` 会生成或读取 `X-Request-Id`，写入：

```text
request attribute
response header
SLF4J MDC
ResponseVO.requestId
```

控制台日志格式会带上 requestId，便于根据一次请求串起排查链路。

## 运行命令

当前推荐使用 IntelliJ 自带 Maven：

```powershell
cd D:\Yuewei\git\YUEWEI\plm-server
& "D:\Yuewei\IntelliJ IDEA 2026.1.2\plugins\maven\lib\maven3\bin\mvn.cmd" test
& "D:\Yuewei\IntelliJ IDEA 2026.1.2\plugins\maven\lib\maven3\bin\mvn.cmd" spring-boot:run
```

OpenAPI：

```text
http://localhost:8080/v3/api-docs
http://localhost:8080/swagger-ui.html
```

## 新增模块放置规则

以后新增模块统一放到：

```text
src/main/java/com/yuewei/plm/module/<moduleName>/
```

标准结构：

```text
module/<moduleName>/
├─ controller/
├─ service/
│  └─ impl/
├─ repository/
├─ entity/
├─ dto/
├─ vo/
├─ validator/
└─ constant/
```

当前 `controller/service/repository` 根目录中的 Product 示例保留作为早期兼容代码。新模块优先按 `module/<moduleName>` 组织。

## 当前骨架边界

已包含：

```text
启动入口
外部化配置
路由分组
健康检查
数据库连接检查
系统日志 requestId
权限中间件骨架
统一响应
统一异常处理
基础参数校验
README 文档
```

未包含：

```text
完整登录
用户表鉴权
BOM 业务
工艺路线业务
项目时间轴推进
文件上传闭环
操作日志落库
ERP / MES 集成
```
