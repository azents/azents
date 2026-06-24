# Azents testenv

Azents local translated test environment. translated translated tooltranslated translated:

- **`preflight.py`** — prerequisites translated (Stage 1a)
- **`devserver.py`** — devserver translated translated (Stage 1b)

> translated translated: azents/azents#2327, azents/azents#2328, azents/azents#2338
> translated document: [Stage 1a](../../docs/azents/design/local-fullstack-test-env.md) · [Stage 1b](../../docs/azents/design/devserver-lifecycle.md)

## E2E entrypoint

azents translated translated verifytranslated default translated E2E translated, testenv translated fallback/diagnostic translated.
E2E translated testenv fixture/readiness/support translated translated translated translated
`testenv/azents/e2e/` translated translated.

```bash
cd testenv/azents/e2e
uv run pytest ./src/tests/azents/public/test_health.py
```

Deterministic CI translated AWS/ECR credential translated next translated translated runtranslated.

```bash
cd testenv/azents/e2e
uv run pytest -vv -m "not live_external" ./src
```

Live/external verifytranslated deterministic CI translated translated translated. PR translated `azents-live-e2e` label translated
translated maintainer translated `/azents-live-e2e` comment translated translated translated workflow translated runtranslated
requesttranslated live check translated processtranslated credential missing translated failuretranslated.
Nightly live workflow translated optional check translated prerequisite not-ready statetranslated skip summary translated translated.
Live workflow translated `live_external` marker translated translated E2E testtranslated runtranslated. GitHub Actions translated `AZENTS_BEDROCK_AWS_ACCESS_KEY_ID`,
`AZENTS_BEDROCK_AWS_SECRET_ACCESS_KEY`, `AZENTS_BEDROCK_AWS_REGION` secret translated translated
`azents-bedrock` shared credentials profile translated materialize translated,
`AZENTS_BROWSER_OAUTH_STORAGE_STATE` secret translated translated Browser/OAuth storage state translated materialize translated.
Browser/OAuth prerequisite translated `AZENTS_PUBLIC_BASE_URL` secret translated `.env` translated materialize translated translated ready translated translated.

## Bootstrap boundary

local default run environmenttranslated `bootstrap local` translated preparetranslated. translated translated non-secret `.env`,
Docker compose infra, current-worktree devserver, `fixture up devserver`, doctor summary translated
translated.

```bash
cd testenv/azents
uv run testenv bootstrap local
```

`bootstrap local` translated external secret create, Tailscale/OAuth login, product DB translated write,
E2E run, secret value outputtranslated translated translated. translateduse product state translated `fixture up <fixture>` translated preparetranslated.

## Prerequisite snapshot

external credential/prerequisite translated translated live E2E translated run translated doctor translated translated calltranslated translated.
translated prepare phase translated contract translated translated snapshot translated translated, consumer translated translated snapshot translated
ready/missing/stale statetranslated translated.

```bash
cd testenv/azents
uv run testenv prerequisite prepare --profile live --json
```

current contract translated Bedrock AWS shared credentials translated Browser/OAuth storage state translated translated translated.
Snapshot translated profile, generated_at, contract hash, worktree fingerprint, check status, guidance translated
safe metadata translated savetranslated access key, secret key, token, password translated savetranslated translated.

# Preflight (`preflight.py`)

prerequisites translated tool.

## usetranslated

`testenv/azents`translated working directorytranslated translated runtranslated:

```bash
cd testenv/azents
python preflight.py
```

Python 3.14 translated translated (translated translated translated). preflighttranslated translated `pyproject.toml`translated
translated translated translated translated `uv sync`translated translated translated.

## Exit codes

| code | translated |
|------|------|
| 0    | translated translated PASS |
| 1    | translated translated FAIL |
| 2    | run translated translated (Python translated translated) |

## output translated

### state translated

TTYtranslated translated·translated, non-TTY(`NO_COLOR=1` translated)translated ASCIItranslated outputtranslated.

| Status | TTY | Non-TTY | translated |
|--------|-----|---------|------|
| PASS   | ✓ (green)  | `[PASS]` | translated translated |
| FAIL   | ✗ (red)    | `[FAIL]` | translated failure — fix hint translated |
| WARN   | ⚠ (yellow) | `[WARN]` | translated translated translated translated |
| SKIP   | ⊘ (dim)    | `[SKIP]` | translated translated failuretranslated translated |

### translated translated failure translated

translated translated translated FAILtranslated translated translated, **translated translated translated translated
translated run**translated **next translated translated SKIP**translated. translated
"Dockertranslated translated translated Postgres connectiontranslated translated"translated translated translated failuretranslated translated
translated. translated translated translated translated translated translated translated checktranslated translated translated.

### `depends_on`

translated translated translated translated translated translated translated translated. translated translated
`postgres-connectable`translated `python-deps-installed`, `postgres-container-healthy`,
`required-env-vars`translated translated. translated translated PASStranslated translated SKIPtranslated translated.

## translated list

| translated | translated id | verify translated |
|----------|---------|-----------|
| system | `repo-root` | monorepo translated run translated |
| system | `docker-running` | Docker daemon translated |
| system | `docker-compose-available` | Docker Compose v2 translated |
| system | `uv-installed` | `uv` CLI |
| system | `tmux-installed` | `tmux` CLI (Stage 1b devserver translated required) |
| system | `python-version` | Python 3.14 translated |
| system | `python-deps-installed` | `python/apps/azents/.venv` translated translated |
| ports | `devserver-ports-free` | 8010, 8011 translated translated |
| config | `env-file-exists` | `testenv/azents/.env` exists |
| config | `required-env-vars` | required `AZ_*` translated + translated key format |
| config | `llm-api-key-set` | OpenAI/Anthropic/Bedrock(AWS) translated exists (WARN) — live chat translated |
| infra | `postgres-container-healthy` | `docker compose ps` state |
| infra | `postgres-connectable` | actual DB connection |
| infra | `valkey-reachable` | `AZ_REDIS_URL` TCP connection |
| infra | `rustfs-reachable` | RustFS `/minio/health/live` (TCP fallback) |
| runtime_state | `db-migration-current` | Alembic `current` vs `heads` |

**translated translated(5433, 6379, 9000)translated translated translated** — composetranslated translated translated
statetranslated translated translated.

## translated translated failure translated

| failure translated | translated | translated |
|-----------|------|------|
| `python-deps-installed` | translated translated | `cd python/apps/azents && uv sync` |
| `env-file-exists` | `.env` missing | `cp testenv/azents/.env.example testenv/azents/.env` translated translated |
| `required-env-vars` / `AZ_CREDENTIAL_ENCRYPTION_KEY` | format error | `python -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())"` |
| `llm-api-key-set` (WARN) | LLM translated translatedsettings | OpenAI: `OPENAI_API_KEY=sk-...`, Anthropic: `ANTHROPIC_API_KEY=...`, Bedrock: `AWS_ACCESS_KEY_ID`+`AWS_SECRET_ACCESS_KEY` translated `AWS_PROFILE` (in `.env`). live chattranslated translated — translated translated translated translated translated |
| `postgres-container-healthy` | container translated | `docker compose -f testenv/azents/docker-compose.yaml up -d db` |
| `valkey-reachable` / `rustfs-reachable` | container translated | `docker compose -f testenv/azents/docker-compose.yaml up -d` |
| `tmux-installed` | tmux translated | `brew install tmux` (macOS) / `sudo apt install tmux` (Debian/Ubuntu) |
| `devserver-ports-free` | translated devservertranslated translatedexists | `lsof -i :8010` translated translated |
| `db-migration-current` | migration translated | `cd python/apps/azents && uv run alembic upgrade head` |

## translated translated translated

1. **translated optional** — translated translated file(`system.py`, `ports.py`, `config.py`,
   `infra.py`, `runtime_state.py`) translated translated filetranslated translated.
2. **`Check` translated** — next translated translated settingstranslated:
   - `id` — translated kebab-case translated
   - `name` — translated translated translated description (translated)
   - `category` — translated string
   - `depends_on` (optional) — translated translated translated `id` translated
3. **`run(context)` translated** — `CheckResult(status=..., message=..., fix_hint=...)`
   translated returntranslated. translated external translatedkeytranslated translated translated (`testenv/azents/pyproject.toml`translated
   translated translated `uv sync`).
4. **`all_checks()`translated register** — `testenv/checks/__init__.py`translated translated translated return translated
   **translated translated translated** translated translated.
5. **read translated** — translated statetranslated translated translated translated (`docker compose up`, `alembic upgrade`
   translated translated).

## translated translated

- **translated none**: translated translated readtranslated translated.
- **Python 3.14**: translated translated translated translated translated translated (`pyproject.toml`translated `requires-python = ">=3.14"`).

---

# Devserver lifecycle (`devserver.py`)

devservertranslated tmux sessiontranslated translated translated/translated/state checktranslated. preflighttranslated translated translated usetranslated.
detail translated [`docs/azents/design/devserver-lifecycle.md`](../../docs/azents/design/devserver-lifecycle.md) reference.

`devserver.py`translated typer translated `uv run` contexttranslated runtranslated. `testenv/azents`translated `uv sync`translated
translated translated.

## Prerequisites

- `tmux` translated (`preflight.py`translated `tmux-installed` translated)
- `testenv/azents/.env` (`.env.example`translated translated translated)
- `testenv/azents/docker-compose.yaml`translated translated (`up`translated translated translated)
- `cd testenv/azents && uv sync`translated translated translated

## translated

`testenv/azents`translated working directorytranslated translated runtranslated.

```bash
cd testenv/azents

# translated(compose) + migration + devserver translated, readytranslated pending
uv run devserver.py up

# translated translated file translated translatedload translated
uv run devserver.py up --reload

# optionaltranslated translated
uv run devserver.py up --no-infra --no-migrate
uv run devserver.py up --timeout 120

# translated session translated translated
uv run devserver.py up --force
uv run devserver.py restart

# state check (shell translated translated translated)
uv run devserver.py status
# exit: 0 = running/ready, 1 = unhealthy, 2 = not running

# graceful translated
uv run devserver.py down
uv run devserver.py down --all     # composetranslated
uv run devserver.py down --force   # translated kill

# translated check
uv run devserver.py logs
uv run devserver.py logs -n 200
uv run devserver.py logs -f

# agent-runtime runtime translated translated (3-5translated, Stage 3 task translated translated)
```

`preflight.py`translated translated cwdtranslated runtranslated translated translated:

```bash
cd testenv/azents && python preflight.py
```

## tmux session translated translated

translatedtime translated translated translated translated translated:

```bash
tmux attach -t azents-testenv-devserver
# translated: Ctrl-b d
```

session internaltranslated Ctrl-ctranslated translated translated graceful shutdowntranslated translated.

## `.state/` translated

`testenv/azents/.state/`translated runtime filetranslated translated (gitignored):

- `devserver.log` — tmux panetranslated stdout/stderr translated append
- `devserver.state.json` — session translateddata

translated translated stale statetranslated translated `up`/`down`translated translated translated cleanup + stderr translated.

## translated translated

`devserver.py`translated translated typer CLItranslated actual translated `testenv/devserverlib/`translated translated translated:

```
testenv/azents/
├── devserver.py           # CLI translated (typer)
└── testenv/devserverlib/    # internal translated
    ├── paths.py           # translatedpath translated + exit code
    ├── env.py             # python-dotenvtranslated .env translated
    ├── state.py           # state.json read/write
    ├── tmux.py            # tmux translated
    ├── compose.py         # docker compose
    ├── alembic.py         # alembic upgrade
    └── readiness.py       # readiness translated + log tail
```

## `python/apps/azents/bin/devserver.sh`translated translated

`bin/devserver.sh`translated **foreground translated**translated translated translated (IDE translated attach, translated translated
translated translated). `devserver.py`translated **translated/agent translated**translated translated orchestratortranslated, translated translated
translated `src/cli/devserver.py`translated calltranslated devserver translated translated translated translated.

| translated | use |
|---|---|
| IDE translated, foreground translated translated | `python/apps/azents/bin/devserver.sh` |
| agent/translated, translated orchestration | `cd testenv/azents && uv run devserver.py up` |

---

# Fixture support (`fixture`)

`testenv fixture` translated E2E translated translatedusetranslated product state readiness translated preparetranslated verifytranslated
support command translated. translated behavior translated primary evidence translated E2E translated, feature QA goaltranslated
pass/fail translated design/issue/PR/report translated translated.

## usetranslated

```bash
cd testenv/azents
uv run testenv fixture doctor agent-basic --json
uv run testenv fixture up agent-basic --json
```

fixture translated translated stale translated `fixture doctor` translated `fixture up/reset` guidance translated returntranslated.
E2E translated translated fixture translated translated preparetranslated translated runtranslated.

---

# Seed library (`testenv/seed/`)

devservertranslated readytranslated statetranslated user/workspace/integration/agenttranslated translated translated translated translated translated translated translated translated translated translated translated. **CLItranslated translated import translated translated**translated (translated translated optionaltranslated [translated document](../../docs/azents/design/seed-helpers.md) translated).

## translated translated (Discussion #2358 §2)

> testenvtranslated e2etranslated translated. e2etranslated fixturetranslated translated translated translated verifytranslated, feature QA goaltranslated evidence translated PRtranslated translated. **translated "translated translated bootstrap"translated translated "agenttranslated translated translated translated translated"translated.**

translated translated = translated translated object. translated translated translated translated. translated `unique()` translated (email/handletranslated uuid suffix).

## Prerequisites

- `cd testenv/azents && uv sync` translated
- `uv run devserver.py up` translated translated + devservertranslated ready state
- translated cwd(`testenv/azents`)translated `uv run python ...`

base URLtranslated environmenttranslated override translated (default localhost):

```bash
export TESTENV_AZENTS_PUBLIC_URL=http://localhost:8010   # default
export TESTENV_AZENTS_ADMIN_URL=http://localhost:8011    # default
```

## translated translated

```
testenv/azents/testenv/seed/
├── __init__.py     # translated (re-export none)
├── client.py       # public_client(), admin_client() translated
├── types.py        # User, Workspace, Integration, Agent (frozen dataclass)
├── unique.py       # unique() — uuid suffix translated
├── auth.py         # create_user
├── workspace.py    # create
├── llm.py          # register_model, create_integration
└── agent.py        # create
```

translated `from testenv.seed.types import User, Workspace` translated **translated import**translated. `__init__.py`translated re-exporttranslated translated translated (translated translated).

## use translated

translated calltranslated translated `TestenvClient` translated translated translated (Stage 2translated translated). `TestenvClient` translated translated DI data containertranslated, `build_client(config)` / `build_client_from_env()` translated translated objecttranslated translated. environment translated `TestenvConfig.from_env()` translated translated translated, translated translated translated translated configtranslated translated.

### translated 1 — user + workspace

```python
from testenv.client import build_client_from_env

c = build_client_from_env()
user = c.auth.create_user()                  # email = test-{unique}@example.com
ws = c.workspace.create(user)                # handle = ws-{unique}
print(user.email, user.access_token, ws.handle)
```

### translated 2 — agenttranslated (LLM translatedcall none, dummy key)

```python
from testenv.client import build_client_from_env

c = build_client_from_env()
user = c.auth.create_user()
ws = c.workspace.create(user)
c.llm.register_model("gpt-4o-mini")             # translated (409 translated)
integration = c.llm.create_integration(user, ws)  # api_key="sk-test-dummy" default
a = c.agent.create(user, ws, integration, "gpt-4o-mini")
print(a.id, a.name)
```

### translated 3 — translated translated, translated workspace member (current translated)

`workspace_v1` APItranslated add_member translated translated 1translated translated translated. add_member APItranslated azents-servertranslated translated `c.workspace.add_member`translated translated translated translated. translated translated [translated document §Feasibility verify §4](../../docs/azents/design/seed-helpers.md#feasibility-verify-result).

### translated 4 — admin client translated use (internaltranslated, token translated)

```python
from testenv.client import build_client_from_env
from testenv.seed.client import admin_client

c = build_client_from_env()
admin = admin_client(c.config)
# admin.<api_v1>.<method>(...) — testenv devservertranslated admin :8011translated auth none
```

### translated 5 — actual LLM calltranslated translated verify

```python
import os
from testenv.client import build_client_from_env

c = build_client_from_env()
user = c.auth.create_user()
ws = c.workspace.create(user)
integration = c.llm.create_integration(
    user, ws, api_key=os.environ["OPENAI_API_KEY"],
)
# Stage 2translated c.chat.collect(...) translated translated translated LLM call
```

## return dataclass

translated `frozen=True`translated mutation translated translated calltranslated translated translated translated.

```python
from testenv.seed.types import User, Workspace, Integration, Agent

@dataclass(frozen=True)
class User:
    email: str
    access_token: str
    refresh_token: str

@dataclass(frozen=True)
class Workspace:
    handle: str
    name: str
    owner: User

@dataclass(frozen=True)
class Integration:
    id: str
    workspace: Workspace
    provider: str        # "openai" translated
    name: str

@dataclass(frozen=True)
class Agent:
    id: str
    workspace: Workspace
    integration: Integration
    name: str
    model_slug: str
```

## translated

- defaulttranslated `unique()` translated translated translated object. translated E2E/feature verification translated translated
- translated DBtranslated translated `uv run devserver.py down --all && uv run devserver.py up`
- compose volumetranslated translated resettranslated translated translated (Stage 1b translated)

## translated test

translated translated/integration test none. translated translated 1/2translated translated translated verify roletranslated translated (Discussion §3.7).

---

# Live library (`testenv/live/`)

seedtranslated translated objecttranslated translated **actual WebSocket chat sessiontranslated translated LLM translated translated translated** verifytranslated translated translated. Stage 2 resulttranslated.

## translated translated

- `testenv/seed/` translated "translated", `testenv/live/` translated "translated"
- **response translated translated event translated translated**translated translated — "translated translated translated"
- translated Session = translated ws connection = translated turn. translated translated `collect`translated translated translated translated ws connectiontranslated translated. translated turntranslated translated `start_session`translated translated call

detail translated: [`docs/azents/design/llm-pipeline.md`](../../docs/azents/design/llm-pipeline.md)

## Prerequisites

- `cd testenv/azents && uv sync` (typer, websockets, OpenAPI client)
- `uv run devserver.py up` translated translated + devserver ready
- (optional) `OPENAI_API_KEY` translated `ANTHROPIC_API_KEY` — **translated `run_completed`/`ordered` translated translated**. `has_text_content`translated real key translated

## translated translated

```
testenv/azents/testenv/live/
├── __init__.py       # docstring only
├── chat.py           # Chat: start_session, collect, stream (Stage 2)
├── tools.py          # Tools: LLM translated tool call translated helper (Stage 3)
├── runtime.py        # Runtime: LLM translated — main + daemon sidecar container translated (Stage 3)
├── mcp.py            # Mcp: mock MCP bind mount + toolkit config (Stage 3)
├── matchers.py       # run_completed, ordered, has_text_content,
│                     # has_function_call, function_call_count,
│                     # function_call_succeeded, function_call_output_contains,
│                     # runtime_exec_ok, runtime_exec_blocked
├── errors.py         # ChatError, ChatConnectionError, ChatTimeout
└── types.py          # Session (frozen dataclass)
```

translated/translated/translated translated translated import:

```python
from testenv.live import chat, matchers
from testenv.live.types import Session
from testenv.live.errors import ChatTimeout, ChatConnectionError
```

## use translated

### translated 1 — dummy keytranslated translated verify (CI translated)

```python
from testenv.client import build_client_from_env
from testenv.live import matchers

c = build_client_from_env()
user = c.auth.create_user()
ws = c.workspace.create(user)
c.llm.register_model("gpt-4o-mini")
integration = c.llm.create_integration(user, ws)        # dummy key default
a = c.agent.create(user, ws, integration, "gpt-4o-mini")

session = c.chat.start_session(user, a)
events = c.chat.collect(session, "Hello, testenv!")
# events: ['run_started', 'error', 'run_complete']

matchers.run_completed(events)                              # OK
matchers.ordered(events, ["run_started", "run_complete"])   # OK
```

### translated 2 — real keytranslated translated responsetranslated verify

```python
import os
from testenv.client import build_client_from_env
from testenv.live import matchers

c = build_client_from_env()
user = c.auth.create_user()
ws = c.workspace.create(user)
c.llm.register_model("gpt-4o-mini")
integration = c.llm.create_integration(
    user, ws, api_key=os.environ["OPENAI_API_KEY"],
)
a = c.agent.create(user, ws, integration, "gpt-4o-mini")

session = c.chat.start_session(user, a)
events = c.chat.collect(session, "translated")

matchers.run_completed(events)
matchers.has_text_content(events)   # real keytranslated translated
matchers.ordered(
    events,
    ["run_started", "content_delta", "text_item", "run_complete"],
)
```

### translated 3 — translated streamtranslated event translated

```python
session = c.chat.start_session(user, a)
for event in c.chat.stream(session, "Hello"):
    print(event.get("type"))
    if event.get("type") == "run_complete":
        break
```

### translated 4 — translated turn

translated Sessiontranslated translated turntranslated translated, translated turntranslated translated Session:

```python
s1 = c.chat.start_session(user, a)
events1 = c.chat.collect(s1, "translated translated")

s2 = c.chat.start_session(user, a)
events2 = c.chat.collect(s2, "translated translated")
```

## translated summary

| translated | translated | real key translated? |
|---|---|---|
| `run_completed(events)` | translated `run_complete` | ✗ dummy key OK |
| `ordered(events, types)` | `types`translated translated translated translated | translated translated dummy key pathtranslated translated (run_started, run_completetranslated OK) |
| `has_text_content(events)` | `text_item` exists + content translated translated | **✓ real key translated** |

## translated translated

```python
from testenv.live.errors import ChatError, ChatConnectionError, ChatTimeout

try:
    events = chat.collect(session, "Hello")
except ChatTimeout as e:
    print(f"timeout, got {len(e.collected_events)} events before")
except ChatConnectionError:
    print("devserver translated translated exists — uv run devserver.py status")
```

## translated

default 60translated. `collect(..., timeout=120)` translated override. LLM translated + tool call translated translated translated translated.
