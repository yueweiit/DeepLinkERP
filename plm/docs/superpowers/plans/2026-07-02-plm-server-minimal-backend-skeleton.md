# PLM Server Minimal Backend Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a minimal runnable Spring Boot backend skeleton for `plm-server` without implementing complete PLM business features.

**Architecture:** Keep the existing Spring Boot 3.5.0 single application and add the missing skeleton layers around it: externalized configuration, request tracing, security middleware skeleton, health route group, unified response/error handling, and basic validation. Existing Product demo endpoints remain untouched unless they must compile against shared infrastructure.

**Tech Stack:** Java 17, Spring Boot 3.5.0, Spring MVC, Spring Security, Spring Validation, MyBatis-Plus 3.5.7, PostgreSQL JDBC, SpringDoc OpenAPI, SLF4J + Logback, Maven.

## Global Constraints

- Do not implement full business features such as login persistence, BOM, workflow, file upload, or project timeline actions.
- Preserve existing runnable Product demo behavior where possible.
- Use `/api/v1` for application APIs.
- Use `ResponseVO<T>` for JSON responses.
- Use `GlobalExceptionHandler` for exception handling.
- Put new skeleton modules under `src/main/java/com/yuewei/plm/module/<moduleName>/`.
- Use framework-supported mechanisms: `SecurityFilterChain`, Spring `Filter`, Spring Validation, Spring profiles, Spring Boot datasource, Spring MVC.
- Do not hardcode production secrets in Java code.

---

## File Structure

### Create

- `plm-server/src/main/java/com/yuewei/plm/common/config/AppProperties.java`  
  Binds project custom configuration under `app.*`.

- `plm-server/src/main/java/com/yuewei/plm/common/filter/RequestContextFilter.java`  
  Generates or propagates `requestId`, writes it to MDC, and exposes it to downstream code.

- `plm-server/src/main/java/com/yuewei/plm/common/security/CurrentUser.java`  
  Minimal current-user value object for middleware skeleton.

- `plm-server/src/main/java/com/yuewei/plm/common/security/CurrentUserContext.java`  
  Thread-local current-user holder.

- `plm-server/src/main/java/com/yuewei/plm/common/security/SimpleTokenAuthenticationFilter.java`  
  Minimal permission middleware skeleton that reads `Authorization: Bearer <token>`.

- `plm-server/src/main/java/com/yuewei/plm/module/health/controller/HealthController.java`  
  Route group for health checks.

- `plm-server/src/main/java/com/yuewei/plm/module/health/vo/HealthVO.java`  
  Health response object.

- `plm-server/src/main/java/com/yuewei/plm/module/health/dto/ValidationProbeDTO.java`  
  DTO for basic validation probe.

- `plm-server/src/test/java/com/yuewei/plm/common/vo/ResponseVOTest.java`  
  Unit test for unified response behavior.

- `plm-server/src/test/java/com/yuewei/plm/module/health/controller/HealthControllerTest.java`  
  MVC test for health and validation routes.

- `plm-server/README.md`  
  Backend skeleton README.

### Modify

- `plm-server/pom.xml`  
  Add Spring Boot Actuator only if needed for health foundation.

- `plm-server/src/main/resources/application.yml`  
  Add environment-variable-backed app, datasource, logging, management, and file-storage defaults.

- `plm-server/src/main/resources/application-dev.yml`  
  Change hardcoded dev values to environment-overridable values.

- `plm-server/src/main/resources/application-prod.yml`  
  Ensure production values use environment placeholders.

- `plm-server/src/main/java/com/yuewei/plm/PlmApplication.java`  
  Enable configuration properties binding.

- `plm-server/src/main/java/com/yuewei/plm/common/config/SecurityConfig.java`  
  Wire the token filter and route authorization rules.

- `plm-server/src/main/java/com/yuewei/plm/common/config/WebMvcConfig.java`  
  Keep existing MVC config compatible with request tracing.

- `plm-server/src/main/java/com/yuewei/plm/common/exception/GlobalExceptionHandler.java`  
  Fix response messages and add security exception handling if needed.

- `plm-server/src/main/java/com/yuewei/plm/common/util/RequestIdUtil.java`  
  Align requestId lookup with the new filter.

---

## Task 1: Unified Response and Exception Foundation

**Files:**
- Create: `plm-server/src/test/java/com/yuewei/plm/common/vo/ResponseVOTest.java`
- Modify: `plm-server/src/main/java/com/yuewei/plm/common/exception/GlobalExceptionHandler.java`

**Interfaces:**
- Consumes: `ResponseVO.success`, `ResponseVO.created`, `ResponseVO.error`
- Produces: clean UTF-8 error messages and consistent response envelopes

- [ ] **Step 1: Write ResponseVO tests**

Create `plm-server/src/test/java/com/yuewei/plm/common/vo/ResponseVOTest.java`:

```java
package com.yuewei.plm.common.vo;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.OffsetDateTime;
import org.junit.jupiter.api.Test;

class ResponseVOTest {

    @Test
    void successWrapsDataWithRequestMetadata() {
        OffsetDateTime now = OffsetDateTime.parse("2026-07-02T10:00:00+08:00");

        ResponseVO<String> response = ResponseVO.success("ok", "req-1", now);

        assertThat(response.getCode()).isZero();
        assertThat(response.getMessage()).isEqualTo("success");
        assertThat(response.getData()).isEqualTo("ok");
        assertThat(response.getRequestId()).isEqualTo("req-1");
        assertThat(response.getTimestamp()).isEqualTo(now);
    }

    @Test
    void errorWrapsCodeMessageAndRequestMetadata() {
        OffsetDateTime now = OffsetDateTime.parse("2026-07-02T10:00:00+08:00");

        ResponseVO<Void> response = ResponseVO.error(40001, "参数校验失败", "req-2", now);

        assertThat(response.getCode()).isEqualTo(40001);
        assertThat(response.getMessage()).isEqualTo("参数校验失败");
        assertThat(response.getData()).isNull();
        assertThat(response.getRequestId()).isEqualTo("req-2");
        assertThat(response.getTimestamp()).isEqualTo(now);
    }
}
```

- [ ] **Step 2: Run the test**

Run:

```powershell
& "D:\Yuewei\IntelliJ IDEA 2026.1.2\plugins\maven\lib\maven3\bin\mvn.cmd" -pl plm-server test -Dtest=ResponseVOTest
```

Expected: PASS, because `ResponseVO` already exists.

- [ ] **Step 3: Fix mojibake messages in GlobalExceptionHandler**

Replace invalid garbled Chinese messages in `GlobalExceptionHandler` with:

```java
"参数校验失败"
"参数错误"
"服务器内部错误"
```

- [ ] **Step 4: Run the targeted test again**

Run:

```powershell
& "D:\Yuewei\IntelliJ IDEA 2026.1.2\plugins\maven\lib\maven3\bin\mvn.cmd" -pl plm-server test -Dtest=ResponseVOTest
```

Expected: BUILD SUCCESS.

---

## Task 2: Externalized Configuration and Request Context

**Files:**
- Create: `plm-server/src/main/java/com/yuewei/plm/common/config/AppProperties.java`
- Create: `plm-server/src/main/java/com/yuewei/plm/common/filter/RequestContextFilter.java`
- Modify: `plm-server/src/main/java/com/yuewei/plm/PlmApplication.java`
- Modify: `plm-server/src/main/java/com/yuewei/plm/common/util/RequestIdUtil.java`
- Modify: `plm-server/src/main/resources/application.yml`
- Modify: `plm-server/src/main/resources/application-dev.yml`
- Modify: `plm-server/src/main/resources/application-prod.yml`

**Interfaces:**
- Produces: `AppProperties`, request attribute `requestId`, response header `X-Request-Id`, MDC key `requestId`

- [ ] **Step 1: Add AppProperties**

Create `AppProperties.java`:

```java
package com.yuewei.plm.common.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "app")
public class AppProperties {

    private final Security security = new Security();
    private final Storage storage = new Storage();

    public Security getSecurity() {
        return security;
    }

    public Storage getStorage() {
        return storage;
    }

    public static class Security {
        private boolean enabled = true;
        private String devToken = "dev-token";

        public boolean isEnabled() {
            return enabled;
        }

        public void setEnabled(boolean enabled) {
            this.enabled = enabled;
        }

        public String getDevToken() {
            return devToken;
        }

        public void setDevToken(String devToken) {
            this.devToken = devToken;
        }
    }

    public static class Storage {
        private String localRoot = "data/uploads";

        public String getLocalRoot() {
            return localRoot;
        }

        public void setLocalRoot(String localRoot) {
            this.localRoot = localRoot;
        }
    }
}
```

- [ ] **Step 2: Enable configuration properties**

Modify `PlmApplication.java` to include:

```java
@EnableConfigurationProperties(AppProperties.class)
```

- [ ] **Step 3: Add request context filter**

Create `RequestContextFilter.java` to:

```java
package com.yuewei.plm.common.filter;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.UUID;
import org.slf4j.MDC;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class RequestContextFilter extends OncePerRequestFilter {

    public static final String REQUEST_ID_ATTRIBUTE = "requestId";
    public static final String REQUEST_ID_HEADER = "X-Request-Id";

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {
        String requestId = request.getHeader(REQUEST_ID_HEADER);
        if (!StringUtils.hasText(requestId)) {
            requestId = UUID.randomUUID().toString();
        }

        request.setAttribute(REQUEST_ID_ATTRIBUTE, requestId);
        response.setHeader(REQUEST_ID_HEADER, requestId);
        MDC.put(REQUEST_ID_ATTRIBUTE, requestId);
        try {
            filterChain.doFilter(request, response);
        } finally {
            MDC.remove(REQUEST_ID_ATTRIBUTE);
        }
    }
}
```

- [ ] **Step 4: Align RequestIdUtil**

Ensure `RequestIdUtil.getRequestId(request)` first reads request attribute `requestId`, then `X-Request-Id`, then generates a UUID fallback.

- [ ] **Step 5: Externalize configuration**

Update configuration files so datasource, security, storage, and logging support environment variables.

- [ ] **Step 6: Run compilation**

Run:

```powershell
& "D:\Yuewei\IntelliJ IDEA 2026.1.2\plugins\maven\lib\maven3\bin\mvn.cmd" -pl plm-server test
```

Expected: BUILD SUCCESS.

---

## Task 3: Security Middleware Skeleton

**Files:**
- Create: `plm-server/src/main/java/com/yuewei/plm/common/security/CurrentUser.java`
- Create: `plm-server/src/main/java/com/yuewei/plm/common/security/CurrentUserContext.java`
- Create: `plm-server/src/main/java/com/yuewei/plm/common/security/SimpleTokenAuthenticationFilter.java`
- Modify: `plm-server/src/main/java/com/yuewei/plm/common/config/SecurityConfig.java`

**Interfaces:**
- Produces: security middleware that reads bearer token and populates `CurrentUserContext`

- [ ] **Step 1: Add current user classes**

Create `CurrentUser` and `CurrentUserContext` as minimal framework skeleton classes.

- [ ] **Step 2: Add SimpleTokenAuthenticationFilter**

Create a filter that:

```text
If app.security.enabled=false, bypass.
If request path is /api/v1/auth/login, /api/v1/health, /swagger-ui, /v3/api-docs, bypass.
If Authorization header equals Bearer <app.security.dev-token>, populate CurrentUserContext with dev engineer user.
Otherwise throw AuthenticationCredentialsNotFoundException.
Always clear CurrentUserContext in finally.
```

- [ ] **Step 3: Wire SecurityConfig**

Update `SecurityConfig` to:

```text
disable CSRF for REST API
permit /api/v1/health/**
permit /swagger-ui/**
permit /v3/api-docs/**
permit /api/v1/auth/login
require authentication for /api/v1/**
add SimpleTokenAuthenticationFilter before UsernamePasswordAuthenticationFilter
```

- [ ] **Step 4: Run tests**

Run:

```powershell
& "D:\Yuewei\IntelliJ IDEA 2026.1.2\plugins\maven\lib\maven3\bin\mvn.cmd" -pl plm-server test
```

Expected: BUILD SUCCESS.

---

## Task 4: Health Route Group and Basic Validation

**Files:**
- Create: `plm-server/src/main/java/com/yuewei/plm/module/health/controller/HealthController.java`
- Create: `plm-server/src/main/java/com/yuewei/plm/module/health/vo/HealthVO.java`
- Create: `plm-server/src/main/java/com/yuewei/plm/module/health/dto/ValidationProbeDTO.java`
- Create: `plm-server/src/test/java/com/yuewei/plm/module/health/controller/HealthControllerTest.java`

**Interfaces:**
- Produces:
  - `GET /api/v1/health`
  - `GET /api/v1/health/db`
  - `POST /api/v1/health/validation-probe`

- [ ] **Step 1: Write HealthControllerTest**

Create tests with MockMvc:

```text
GET /api/v1/health returns code=0 and data.status=UP.
POST /api/v1/health/validation-probe with blank name returns 400 and code=40001.
POST /api/v1/health/validation-probe with valid name returns code=0.
```

- [ ] **Step 2: Run test and verify RED**

Run:

```powershell
& "D:\Yuewei\IntelliJ IDEA 2026.1.2\plugins\maven\lib\maven3\bin\mvn.cmd" -pl plm-server test -Dtest=HealthControllerTest
```

Expected: FAIL because controller does not exist yet.

- [ ] **Step 3: Implement minimal health DTO/VO/controller**

Implement:

```text
HealthVO(status, application, profile, database, timestamp)
ValidationProbeDTO(name with @NotBlank and @Size)
HealthController with DataSource connection validation for /db
```

- [ ] **Step 4: Run test and verify GREEN**

Run:

```powershell
& "D:\Yuewei\IntelliJ IDEA 2026.1.2\plugins\maven\lib\maven3\bin\mvn.cmd" -pl plm-server test -Dtest=HealthControllerTest
```

Expected: BUILD SUCCESS.

---

## Task 5: README Documentation and Full Verification

**Files:**
- Create or modify: `plm-server/README.md`

**Interfaces:**
- Produces: developer-readable backend skeleton documentation.

- [ ] **Step 1: Write README**

README must include:

```text
Backend language and framework
Directory tree
Directory responsibility
Which folders are Spring Boot/framework recommended
Which folders are Yuewei PLM custom
Environment variables
Run commands
Health check commands
Security token behavior
Unified response format
Unified error handling
Database connection notes
Next module placement rules
```

- [ ] **Step 2: Run full backend tests**

Run:

```powershell
& "D:\Yuewei\IntelliJ IDEA 2026.1.2\plugins\maven\lib\maven3\bin\mvn.cmd" -pl plm-server test
```

Expected: BUILD SUCCESS.

- [ ] **Step 3: Start backend**

Run:

```powershell
& "D:\Yuewei\IntelliJ IDEA 2026.1.2\plugins\maven\lib\maven3\bin\mvn.cmd" -pl plm-server spring-boot:run
```

Expected: application starts on port 8080.

- [ ] **Step 4: Manual smoke test**

Run:

```powershell
Invoke-RestMethod http://localhost:8080/api/v1/health
Invoke-RestMethod http://localhost:8080/v3/api-docs
```

Expected: health returns `code=0`; OpenAPI returns API document.

---

## Self-Review

- Spec coverage: startup entry, env config, route grouping, README, health route, database connection, logs, permission middleware, response, errors, validation are covered.
- Scope check: no complete business features are implemented.
- Type consistency: `ResponseVO`, `HealthVO`, `ValidationProbeDTO`, `AppProperties`, `CurrentUserContext` are used consistently.
- Placeholder scan: no TBD or TODO markers are intentionally left in tasks.
