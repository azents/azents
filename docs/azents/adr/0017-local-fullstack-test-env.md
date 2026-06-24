---
title: "ADR-0017: Full-Stack Local Test Environment — Discussion Record"
created: 2026-04-06
tags: [infra, backend]
updated: 2026-04-06
---

# ADR-0017: Full-Stack Local Test Environment — Discussion Record

> 📌 **Related design document**: [local-fullstack-test-env.md](../design/local-fullstack-test-env.md)
>
> This document records design-stage discussion.

> Related issues: azents/azents#2327 (parent), azents/azents#2328 (Stage 1a)

## Background

Most NoIntern functionality can currently be tested realistically **only after deployment**. We want an environment where an agent, such as Claude Code, can implement a new feature, run the server locally, verify behavior, and directly reproduce bugs.

Goals:

- The primary goal is **environment setup**, not writing test code.
- After implementing a feature, the agent should be able to set up the environment → verify behavior → reproduce bugs.
- Full-stack scope includes MCP and browser testing with Playwright.

## Scope Clarification

### Test Targets, by Priority

**Tool/infrastructure layer**, deterministic:

1. Whether the intended prompt is correctly injected into the Agent.
2. Whether a tool works successfully when the Agent calls it.
3. Whether MCP / external integration toolkits work correctly.
4. Whether the Sandbox behaves as intended.

**LLM pipeline layer**, structural verification only:

1. Whether LLM requests are sent correctly, responses come back normally, and rendering works.
2. Whether image generation from LLM arrives correctly.
3. Whether image input is passed to the LLM in the intended shape.

### Out of Scope

- **LLM response quality evaluation** — realistically not our domain.
- Validation of nondeterministic response contents.

### Core Insight

> There is a contradiction in "an LLM testing an LLM." Claude Code cannot judge how "smart" an agent response is. But if the goal is redefined as verifying **whether the pipeline runs end to end**, the problem becomes solvable. Claude Code acts as an **infrastructure/pipeline engineer**, not as a judge of LLM response quality.

Things Claude Code can catch deterministically:

- Server startup failures, such as config, import, or migration problems.
- API contract breakage, such as 404, schema, or auth problems.
- WebSocket handshake failures.
- Tool execution infrastructure failures, such as Agent Home or daemon communication.
- MCP connection failures, such as config parsing or proxy startup.
- DB schema mismatch.
- Broker pipeline failures.

## Research Summary

### Current Infrastructure Readiness

| Component | State | Notes |
|---|---|---|
| Docker Compose infrastructure | Exists | PostgreSQL (5433), Valkey (6379), RustFS (9000), File-API (8081) |
| devserver.py | Exists | All-in-one Public API (8010) + Admin API (8011) + Engine Worker |
| agent-runtime image | Dockerfile exists | Includes Sandbox Daemon + MCP Proxy + Playwright; needs build |
| OpenAPI clients | Exist | Auto-generated for both Python and TypeScript |
| E2E test pattern | Exists | `nointern-e2e` conftest.py / utils.py can be reused |
| **Local full-stack execution automation** | **Missing** | No guide/skill usable by agents |

### Major Technical Points

- **devserver**: runs Public/Admin API + Engine Worker + Scheduler in one asyncio process. Supports `--reload`.
- **Graceful shutdown**: SIGTERM → wait up to 30 seconds for ongoing engine.run to finish. Do not use `kill -9`.
- **Required environment variables**: `NI_RDB_*`, `NI_AUTH_JWT_SECRET_KEY`, `NI_CREDENTIAL_ENCRYPTION_KEY`, `NI_AGENT_HOME_K8S_MCP_PROXY_IMAGE`, `NI_AGENT_HOME_K8S_SANDBOX_DAEMON_IMAGE`.
- **agent-runtime image**: build takes about 3-5 minutes, size about 700MB-1GB. Chromium binary is installed at runtime.
- **Agent Home Docker**: `sandbox-restricted` bridge network, 512MB/0.5 CPU per container.
- **MCP**: config.json bind mount + mcp-proxy sidecar managed by supervisord.
- **WebSocket chat**: issue ticket with 30-second HMAC → connect → JSON event stream.
- **Docker Compose project name**: `nointern`, usable for container filtering.
- **Health endpoints**: `/health/v1/readiness`, `/health/v1/liveness`; simple responses with no DB/Redis dependency.

## Scenario Configuration Matrix

| | Infra | devserver | agent-runtime | LLM Key | nointern-web |
|---|:-:|:-:|:-:|:-:|:-:|
| A. API CRUD / prompt assembly | O | O | - | - | - |
| B. WebSocket chat / LLM pipeline | O | O | - | O | - |
| C. Shell/file tool execution | O | O | O | O | - |
| D. MCP toolkit | O | O | O | O | - |
| E. Sandbox isolation verification | O | O | O | - | - |
| F. Image generation/input | O | O | - | O | - |
| G. Web UI with Playwright MCP | O | O | - | - | O |

## Discussion Points and Decisions

### 1. Starting Stage / Roadmap

**Background**: Building every scenario at once would explode complexity. We need to build incrementally.

**Decision**: **4-stage roadmap**. Start with Stage 1 and expand sequentially.

```text
Stage 1: Start devserver + API calls + preflight checks
    ├─ Automatic infra start/stop
    ├─ DB migration automation
    ├─ Run devserver in background + health check
    └─ Basic API calls + prompt assembly verification

Stage 2: LLM pipeline (WebSocket chat)
    ├─ LLM API key management
    ├─ WebSocket client helper
    ├─ Create chat session + send/receive messages
    ├─ Event stream verification
    └─ Image input/generation verification

Stage 3: Tool execution + Sandbox
    ├─ agent-runtime image build automation
    ├─ Verify Agent Home container behavior
    ├─ Verify Shell/file tool execution
    ├─ Verify Sandbox isolation
    └─ Verify MCP toolkit behavior

Stage 4: Browser / frontend (optional)
    ├─ Run nointern-web locally
    └─ Verify UI through Playwright MCP
```

**Rationale**: Reliably starting the devserver is the foundation for every test, so Stage 1 is the prerequisite.

### 2. First Deliverable for Stage 1

**Background**: Stage 1 is still broad, so we need to decide where to start.

**Decision**: Start with a **preflight check mechanism**.

**Rationale**:

- Before testing, we must know whether the environment is ready.
- We cannot list every prerequisite up front, so we need a mechanism that can grow incrementally.
- The key value is a structure where new checks can be added easily.

### 3. Preflight Location

**Background**: Where should scripts/docs live?

**Options**:

- A. `testenv/nointern/`, top-level repository path
- B. `python/apps/nointern/testenv/`, app-scoped
- C. `docker/nointern/testenv/`
- D. `scripts/local-test/`

**Decision**: **A. `testenv/nointern/`**

**Rationale**:

- `docker-compose.nointern.yaml` is at the repository root, so operating at the same level keeps paths simple.
- Matches top-level concern-based directories such as `python/`, `docker/`, and `infra/`.
- Allows future expansion such as `testenv/azents/`.
- The environment needs to touch items outside the nointern Python app, such as docker-compose, agent-runtime, and nointern-web, so placing it inside the Python subdirectory is awkward.

### 4. Entrypoint Invocation Method

**Background**: How should preflight be executed?

**Options**:

- A. Direct script execution: `./testenv/nointern/preflight.py`
- B. Makefile: `make preflight`
- C. Root dispatcher: `./testenv/preflight nointern`

**Decision**: **A. direct script execution**

**Rationale**:

- Stage 1 should start simple. Makefile/dispatcher would be over-engineering.
- Consider adding Makefile later when multiple commands such as up, down, and status exist.
- Humans and agents use the same interface.

### 5. Initial Check List

**Background**: Which prerequisites should Stage 1 check?

**Decision**: **15 checks with category numbers**

```text
00-repo-root                       # running from monorepo root
10-docker-running                  # Docker daemon is running
11-docker-compose-available        # docker compose plugin
12-uv-installed                    # uv package manager
13-python-version                  # Python 3.13+
14-python-deps-installed           # uv sync completed
20-devserver-ports-free            # 8010 and 8011 are free
30-env-file-exists                 # .env file exists
31-required-env-vars               # NI_* variables configured
40-postgres-container-healthy      # docker compose state
41-postgres-connectable            # real host connection + auth
42-valkey-reachable                # TCP port check
43-rustfs-reachable                # HTTP health check
44-file-api-healthy                # HTTP /health
70-db-migration-current            # alembic current == heads
```

**Rationale**:

- Numeric prefixes control ordering automatically, with gaps of 10 for easy insertion later.
- 10s: system, 20s: ports, 30s: config, 40s: infra, 70s: runtime state.
- Only devserver ports 8010 and 8011 are checked as "free." Infra ports are expected to be used by `docker compose`, so they are verified in the 40s.
- Real connection check 41 is required separately from container health check 40, because port binding/auth problems are not caught by 40 alone.

### 6. Depth of Environment Variable Value Validation

**Background**: How deeply should `.env` values be validated?

**Options**:

- Level 1: existence only
- Level 2: value format, such as Fernet key or URL scheme
- Level 3: actual connectivity/usability

**Decision**: **Level 1 + Level 2 only for `NI_CREDENTIAL_ENCRYPTION_KEY`**

**Rationale**:

- Most bugs are missing values or typos, so Level 1 is enough.
- If `NI_CREDENTIAL_ENCRYPTION_KEY` has the wrong format, devserver can silently die at startup, so format validation is valuable as an exception.
- Other cases are covered by check 41, real connection validation, so duplicating them is unnecessary.

### 7. Behavior on Failure

**Background**: What should happen when a check fails?

**Options**:

- A. Continue to the end even after failures, showing all problems at once.
- B. Stop immediately on first failure.
- C. Stop by category.

**Decision**: **C. stop by category**

**Rationale**:

- Avoid meaningless failures such as checking postgres when Docker is not running.
- Within the same category, independent problems can still be shown together.
- Numeric prefixes naturally define categories.

### 8. Dependency Checks (`DEPENDS_ON`)

**Background**: Some checks need dependencies even inside categories, such as 70 depending on 14+41.

**Decision**: **Combine category defaults with explicit per-check dependencies through a `depends_on` attribute**

**Rationale**:

- Default to category-level dependencies for simplicity.
- Declare `depends_on=[...]` only for necessary checks such as 41 and 70.
- Only two dependencies are currently needed, so this is not over-engineering.

### 9. `.env` Loading Timing

**Background**: When should environment variables be loaded?

**Decision**: **The runner loads them immediately after check 30 (`env-file-exists`) passes**

- Inject into `os.environ` for subprocess inheritance.
- Store in `RunContext.env` dict for explicit access.

**Rationale**: If check 30 fails, do not load anything. From check 31 onward, environment variables are available.

### 10. Implementation Language

**Background**: Using bash for the check runner/aggregation would create subprocess/IPC complexity and end up imitating a module system.

**Options**:

- bash + source-based modules (`source lib/check.sh`)
- bash + independent scripts with exit-code aggregation
- **Python standard library**
- Bash + Python hybrid, where Python calls bash

**Decision**: **Python standard library**

**Rationale**:

- Requirements such as aggregation, category skip, per-check dependencies, `.env` loading, and output formatting are not clean in bash.
- Python 3 exists by default in Linux/macOS development environments, so it is not an external dependency.
- It runs independently of `uv`/project dependencies and can itself check `python-deps-installed`.
- Check 13 verifies Python 3.13, but preflight itself runs in Python. With stdlib only, Python 3.8+ is sufficient as a minimum.
- Future JSON output, parallel execution, and complex dependency graphs are natural.

### 11. Check Definition Method

**Background**: How should checks be registered in Python?

**Options**:

- A. Class inheritance (`class DockerRunning(Check)`)
- B. Decorator registration (`@register(...)`)
- C. Module-level functions + explicit list

**Decision**: **A. class inheritance + explicit `ALL_CHECKS` list**

**Rationale**:

- Decorators rely on import side-effect based auto-discovery, which the user dislikes.
- Class inheritance is idiomatic Python and makes metadata explicit as attributes.
- An explicit list, `ALL_CHECKS = [DockerRunning(), ...]`, controls both order and registration in one place.
- Adding a new check has two steps: define the class and add it to the list.

### 12. Metadata Method + Instance vs Class List

**Decision**:

- Metadata: **class attributes** (`id`, `name`, `category`, `depends_on`)
- `ALL_CHECKS`: **instance list** (`[DockerRunning(), ...]`)

**Rationale**: Metadata is constant and not instance-specific, so class attributes are the accurate representation. An instance list makes construction timing explicit and easier to debug.

### 13. RunContext Design

**Decision**:

```python
@dataclass
class RunContext:
    repo_root: Path
    nointern_dir: Path
    env_file: Path
    env: dict[str, str]
    previous_results: dict[str, CheckResult]
```

- `.env` is injected into `os.environ` and also kept in `context.env` as a dict.
- Include `previous_results`, but checks should use it directly only as an exception. `depends_on` declarations are the default.

### 14. Output Format

**Decision**:

- If TTY, use color + Unicode symbols. Otherwise, use plain ASCII with automatic detection.
- **Language: English**, following the CLAUDE.md rule that logs/user messages are English.
- For agents, use exit code + human-readable stdout. JSON flag can be added later.

## Remaining Questions Deferred to Stage 2+

- LLM API key management method (Stage 2)
- agent-runtime image build automation trigger (Stage 3)
- Whether and how to include nointern-web (Stage 4)
- devserver process management, such as PID file, tmux, or systemd; decide when adding up/down commands after Stage 1
