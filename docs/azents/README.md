---
title: "azents"
---
# azents

An **Agent Builder SaaS** for creating AI agents with only a system prompt and tool set, then using those agents collaboratively from messaging platforms such as Slack.

## Core Differentiators

- **Credential Isolation**: Agents can never access credentials. Prompt injection has no exfiltration path.
- **Team-Native**: Team memory, per-user memory, and trigger-based permissions are built in from the beginning.
- **Memory Transparency**: Change notifications, revert support, and history tracking.
- **Channel-Agnostic**: Use the same agent from Slack, Discord, KakaoTalk, and other channels.
- **Simplicity**: System prompt + tools = agent. No flowcharts or code required.

## Technology Stack

- **Framework**: FastAPI
- **Database**: PostgreSQL (SQLAlchemy Async)
- **Frontend**: Next.js 16 + Mantine 8 + tRPC
- **Object Storage**: AWS S3 (aioboto3)
- **Tool Layer**: MCP (Model Context Protocol)
- **Monitoring**: Sentry
- **Package Manager**: uv (Python), pnpm (TypeScript)

## Quick Start

### 1. Configure Environment

```bash
cd python/apps/azents
cp .env.example .env
# Edit .env and set environment variables.
```

### 2. Install Dependencies

```bash
uv sync
```

### 3. Set Up the Database

Run local PostgreSQL with Docker Compose:

```bash
# From the repository root
docker compose -f docker-compose.azents.yaml up -d
```

### 4. Run Migrations

```bash
cd db-schemas/rdb
uv run alembic upgrade head
```

### 5. Run Servers

**Public API** (port 8010):
```bash
uv run uvicorn apiserver:app --reload --port 8010
```

**Admin API** (port 8011):
```bash
uv run uvicorn adminserver:app --reload --port 8011
```

### 6. View API Documentation

**Public API:**
- Swagger UI: http://localhost:8010/docs/swagger
- ReDoc: http://localhost:8010/docs/redoc

**Admin API:**
- Swagger UI: http://localhost:8011/docs/swagger
- ReDoc: http://localhost:8011/docs/redoc

## API Server Structure

azents separates the **Public API** and **Admin API**:

| API | Port | Purpose | Entrypoint |
|-----|------|------|-------------|
| **Public** | 8010 | Client applications | `apiserver.py` |
| **Admin** | 8011 | Administrative tools (CRUD) | `adminserver.py` |

## Project Structure

```text
azents/
├── apiserver.py           # Public API entrypoint
├── adminserver.py         # Admin API entrypoint
├── pyproject.toml         # Project configuration
├── src/azents/
│   ├── app.py             # FastAPI app factory
│   ├── core/              # Configuration and dependencies
│   ├── clients/           # External service clients
│   ├── rdb/               # Database layer
│   ├── repos/             # Repositories for data access
│   ├── services/          # Services and business logic
│   ├── api/
│   │   ├── public/        # Public API routes
│   │   └── admin/         # Admin API routes
│   └── utils/             # Utilities
└── db-schemas/            # Alembic migrations
```

See [architecture.md](./design/architecture.md) for a more detailed architecture overview.

## Documentation Structure

Documents are managed through YAML frontmatter such as `title`, `tags`, `created`, and `updated`.
See [AGENTS.md](./AGENTS.md) for the directory structure.

## Environment Variables

| Variable | Required | Default | Description |
|--------|------|--------|------|
| `AZ_RUNTIME_ENV` | N | `local` | Runtime environment (`local`, `deployed`) |
| `AZ_SENTRY_DSN` | N | - | Sentry DSN |
| `AZ_RDB_HOST` | Y | - | PostgreSQL host |
| `AZ_RDB_PORT` | N | `5432` | PostgreSQL port |
| `AZ_RDB_USER` | Y | - | PostgreSQL user |
| `AZ_RDB_PASSWORD` | N | - | PostgreSQL password |
| `AZ_RDB_DB_NAME` | Y | - | PostgreSQL database name |
| `AZ_RDB_USE_IAM_AUTH` | N | `False` | Use RDS IAM authentication |
| `AZ_AUTH_JWT_SECRET_KEY` | Y | - | JWT signing key |
| `AZ_CREDENTIAL_ENCRYPTION_KEY` | Y | - | Fernet encryption key (base64-encoded 32 bytes) |

## Development Workflow

### Add a New Feature

1. Add a repository under `repos/` for data access.
2. Add a service under `services/` for business logic.
3. Add routes under `api/` for HTTP endpoints.

### Create a Migration

```bash
cd db-schemas/rdb
uv run alembic revision --autogenerate -m "description"
```

### Code Quality Checks

```bash
# Lint
uv run ruff check src

# Type check
uv run pyright

# Format
uv run ruff format src
```
