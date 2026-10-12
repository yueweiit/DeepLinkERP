# Docker Compose Full Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `docker compose up -d` start a complete local stack with the phone-watch web service and a PostgreSQL database.

**Architecture:** Keep the existing Python web container as the application service and add a first-class `postgres` service in Compose. The app defaults to connecting to the internal Compose hostname `postgres`, while still allowing `.env` overrides for external PostgreSQL deployments.

**Tech Stack:** Docker, Docker Compose, Python 3.11, PostgreSQL 16, pg8000, Playwright Chromium.

## Global Constraints

- Do not write real PostgreSQL passwords or DingTalk secrets into code or docs.
- Do not delete existing `.env`, `.env.baota`, `data/`, `logs/`, or database files.
- Keep external PostgreSQL deployment possible by overriding `.env`.
- Do not change business Python code for this task.
- Verify Docker Compose syntax with `docker compose config`.

---

### Task 1: Compose Full Stack

**Files:**
- Modify: `docker-compose.yml`

**Interfaces:**
- Produces service `postgres` with host name `postgres`.
- Keeps service `phone-watch` exposed on `${PORT:-8000}:8000`.

- [ ] **Step 1: Update `docker-compose.yml`**

Set the Compose file to:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    container_name: phone-watch-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${PHONE_WATCH_PG_DATABASE:-phone_scraper}
      POSTGRES_USER: ${PHONE_WATCH_PG_USER:-postgres}
      POSTGRES_PASSWORD: ${PHONE_WATCH_PG_PASSWORD:-phone_watch_dev_password}
      POSTGRES_INITDB_ARGS: "--encoding=UTF8 --locale=C"
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
    volumes:
      - phone_watch_pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${PHONE_WATCH_PG_USER:-postgres} -d ${PHONE_WATCH_PG_DATABASE:-phone_scraper}"]
      interval: 10s
      timeout: 5s
      retries: 5

  phone-watch:
    build: .
    container_name: phone-watch
    restart: unless-stopped
    env_file:
      - path: .env
        required: false
    environment:
      PHONE_WATCH_DB_BACKEND: ${PHONE_WATCH_DB_BACKEND:-postgres}
      PHONE_WATCH_PG_DRIVER: ${PHONE_WATCH_PG_DRIVER:-pg8000}
      PHONE_WATCH_PG_HOST: ${PHONE_WATCH_PG_HOST:-postgres}
      PHONE_WATCH_PG_DATABASE: ${PHONE_WATCH_PG_DATABASE:-phone_scraper}
      PHONE_WATCH_PG_USER: ${PHONE_WATCH_PG_USER:-postgres}
      PHONE_WATCH_PG_PASSWORD: ${PHONE_WATCH_PG_PASSWORD:-phone_watch_dev_password}
      PHONE_WATCH_PG_PORT: ${PHONE_WATCH_PG_PORT:-5432}
      PHONE_WATCH_PG_OPTIONS: ${PHONE_WATCH_PG_OPTIONS:--c client_encoding=utf8}
      PHONE_WATCH_PG_CONNECT_TIMEOUT: ${PHONE_WATCH_PG_CONNECT_TIMEOUT:-10}
    depends_on:
      postgres:
        condition: service_healthy
    ports:
      - "${PORT:-8000}:8000"
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    command: python -m phone_watch serve --host 0.0.0.0 --port 8000

volumes:
  phone_watch_pg_data:
```

- [ ] **Step 2: Verify compose syntax**

Run:

```powershell
docker compose config
```

Expected: exit code 0, services include `phone-watch` and `postgres`.

---

### Task 2: Environment Example

**Files:**
- Modify: `.env.example`

**Interfaces:**
- Documents local Docker defaults.
- Keeps placeholders for real production secrets.

- [ ] **Step 1: Update `.env.example`**

Set PG defaults for Compose-local startup:

```text
PHONE_WATCH_DB_BACKEND=postgres
PHONE_WATCH_PG_DRIVER=pg8000
PHONE_WATCH_PG_HOST=postgres
PHONE_WATCH_PG_DATABASE=phone_scraper
PHONE_WATCH_PG_USER=postgres
PHONE_WATCH_PG_PASSWORD=phone_watch_dev_password
PHONE_WATCH_PG_PORT=5432
POSTGRES_PORT=5432
```

Retain DingTalk placeholder values, not real secrets.

- [ ] **Step 2: Verify no real secrets were introduced**

Inspect `.env.example` and ensure values are placeholders or local dev defaults only.

---

### Task 3: Docker Documentation

**Files:**
- Modify: `DOCKER_DEPLOY.md`

**Interfaces:**
- Main command becomes `docker compose up -d --build`.
- Initialization command remains `docker compose run --rm phone-watch python -m phone_watch init-db`.

- [ ] **Step 1: Rewrite Docker deployment guide**

Document:

```powershell
copy .env.example .env
docker compose up -d --build
docker compose run --rm phone-watch python -m phone_watch init-db
docker compose run --rm phone-watch python -m phone_watch check-db
```

Also document:

```powershell
docker compose logs -f phone-watch
docker compose logs -f postgres
docker compose down
```

- [ ] **Step 2: Include external PostgreSQL override note**

Explain that production can still use external PG by setting `PHONE_WATCH_PG_HOST` to the external host and optionally not exposing/using the bundled PG service.

---

### Task 4: Final Verification

**Files:**
- Validate: `docker-compose.yml`, `.env.example`, `DOCKER_DEPLOY.md`

- [ ] **Step 1: Run compose config**

Run:

```powershell
docker compose config
```

Expected: exit code 0.

- [ ] **Step 2: Run Python compile check**

Run:

```powershell
py -m compileall phone_watch tests
```

Expected: exit code 0.

- [ ] **Step 3: Summarize**

Report:

- Changed files.
- Verification commands and results.
- Any unverified Docker build/run steps if not run.
