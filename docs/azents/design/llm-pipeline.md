---
title: "Full-stack Local Test Environment — Stage 2 (LLM Pipeline)"
tags: [infra, backend]
created: 2026-04-08
updated: 2026-04-08
implemented: 2026-04-08
---

# Full-stack Local Test Environment — Stage 2 (LLM Pipeline)

> Related issues: azents/azents#2327 (parent), azents/azents#2376 (implementation)
>
> Discussion: azents/azents#2378 (Phase 1·1.5 complete)
>
> Prior: [Stage 1a Preflight](./local-fullstack-test-env.md), Stage 1b devserver (#2338), Stage 1c seed (#2351)

## Overview

With Stage 1a/1b/1c, agent can now perform **clean state → infra+devserver start → user/workspace/agent seed** in one flow. Stage 2 verifies that LLM pipeline (Engine Worker → LLM provider → broker → ws) runs end-to-end by **opening WebSocket chat session, sending one message, then observing event stream**.

### Core Principle (#2327)

> The contradiction of "LLM testing LLM" — CC cannot judge "smartness" of response content. Instead, structurally verify **whether pipeline runs to end** (events arrive in expected order).

Stage 2 asserts only "which type of events were received". Whether text content is meaningful is out of scope.

## Usage Scenario

```python
import os
from seed import auth, workspace, llm, agent
from live import chat, matchers

# 1. Stage 1c seed building blocks
user = auth.create_user()
ws = workspace.create(user)
llm.register_model("gpt-4o-mini")
integration = llm.create_integration(
    user, ws, api_key=os.environ["OPENAI_API_KEY"],
)
a = agent.create(user, ws, integration, "gpt-4o-mini")

# 2. Stage 2 chat — create WebSocket session + send message + collect events
session = chat.start_session(user, a)
events = chat.collect(session, "Hello, testenv!")

# 3. structural verification (do not verify response content)
matchers.run_completed(events)
matchers.has_text_content(events)
matchers.ordered(events, ["run_started", "content_delta", "run_complete"])

# (optional) low-level stream control
for ev in chat.stream(session, "Again"):
    print(ev["type"])
    if ev["type"] == "run_complete":
        break
```

## Decision Summary

See Discussion #2378 for detailed rationale.

| # | Point | Decision |
|---|---|---|
| §2 | WebSocket vs browser | **C — separate Stage 2 ws, Stage 4 browser** |
| §3.1 | module granularity | **B — new top-level `live` package** |
| §3.2 | sync/async | **A — sync-only** (`websockets.sync`) |
| §3.3 | event collection | **C — `collect` primary + `stream` low-level in parallel** |
| §3.4 | timeout/failure | default 60s, `ChatTimeout(collected_events=...)`, `ChatConnectionError` |
| §3.5 | LLM API key | **A — caller passes explicitly** (Stage 1c pattern) |
| §3.6 | matcher | **C — raw + matcher in parallel** |
| §3.7 | image | **C — text first, add image phase within same Stage 2** |
| §3.8 | preflight `llm-api-key-set` | **C — preflight WARN + chat failure message in parallel** |

## Architecture

```mermaid
flowchart LR
    Agent([Agent]) -->|seed| Seed[seed.*]
    Seed -->|User, Workspace,<br/>Integration, Agent| Obj[(domain objects)]

    Agent -->|chat.start_session| Chat[live.chat]
    Obj --> Chat

    Chat -->|1. chat_v1_issue_ws_ticket| Public[Public API :8010]
    Public -->|ticket| Chat

    Chat -->|2. ws connect<br/>/chat/v1/sessions/<br/>{session_id}?ticket=| WS[WebSocket]
    WS --> Worker[Engine Worker]
    Worker --> LLM[LLM Provider]
    LLM --> Worker
    Worker --> Broker
    Broker -->|run_started,<br/>content_delta,<br/>text_item,<br/>run_complete, ...| WS
    WS --> Chat

    Chat -->|collect → list[dict]| Agent
    Agent -->|matchers.*| Matchers[live.matchers]
    Matchers --> Agent

    Chat -.->|import error path| Errors[live.errors]
    Errors -.->|ChatTimeout, ChatConnectionError| Agent
```

Break existing e2e `create_chat_session` flow (ticket issue → ws connect → send init message → session polling) into building blocks and place into `start_session`; separate event stream collection into `collect`/`stream`.

## Data Model

`Session` dataclass (frozen):

```python
@dataclass(frozen=True)
class Session:
    """Open chat session."""
    id: str                  # session_id (uuid hex)
    user: User               # token owner
    agent: Agent             # conversation target
    public_url: str          # http://localhost:8010 (env override possible)
```

`start_session` returns `Session`, and it is passed as argument to `collect`/`stream`.

## Module Layout

```
testenv/nointern/
├── seed/                       # existing (Stage 1c)
├── live/                       # new (Stage 2)
│   ├── __init__.py             # docstring only (no re-export, Stage 1c rule)
│   ├── chat.py                 # start_session, collect, stream
│   ├── matchers.py             # run_completed, has_text_content, ordered
│   ├── errors.py               # ChatError, ChatTimeout, ChatConnectionError
│   └── types.py                # Session dataclass
├── checks/
│   └── config.py               # + LLMApiKeyAvailable (WARN)
└── pyproject.toml              # pyright include += ["live"]
```

`live/` is ordinary module layout without underscore, like Stage 1c `seed/`.

## Function Signatures

### `live/chat.py`

```python
from live.types import Session
from seed.types import User, Agent

def start_session(user: User, agent: Agent) -> Session:
    """
    1. `chat_v1_issue_ws_ticket(Authorization: Bearer {user.token})` → ticket
    2. `session_id = uuid4().hex`
    3. ws connect `ws://{host}:{port}/chat/v1/sessions/{session_id}?ticket=...`
    4. send init message `{"agent_id": agent.id, "message": "init"}`
    5. close ws (session itself remains on server)
    6. return `Session(id, user, agent, public_url)`

    Extract ticket+init part from e2e `create_chat_session`.
    """


def collect(
    session: Session,
    message: str,
    *,
    until: str = "run_complete",
    timeout: float = 60.0,
) -> list[dict]:
    """Send message and blockingly collect until `until` event arrives.

    - reconnect ws (chat ticket is session-independent, so issue new ticket for each call)
    - send `{"message": message, "role": "user"}`
    - parse into event dict in recv loop → accumulate in list
    - when `event["type"] == until`, return including that event
    - on timeout: `raise ChatTimeout(collected_events=...)`
    - on ws error: `raise ChatConnectionError(...)`
    """


def stream(
    session: Session,
    message: str,
    *,
    timeout: float = 60.0,
) -> Iterator[dict]:
    """Send message and yield events one by one.

    Caller controls with for loop + break. Timeout and error handling same as `collect`.
    Internally, `collect` consumes this iterator and builds list.
    """
```

### `live/matchers.py`

```python
def run_completed(events: list[dict]) -> None:
    """Check last event is `run_complete`. Otherwise AssertionError."""


def has_text_content(events: list[dict]) -> None:
    """Check there is at least one `text_item` event and its content is non-empty."""


def ordered(events: list[dict], expected_types: list[str]) -> None:
    """Check `expected_types` order appears in events (not necessarily contiguous, partial order)."""
```

Start with these 3. Add only as needed — avoid over-abstracting.

### `live/errors.py`

```python
class ChatError(Exception):
    """Base."""


class ChatConnectionError(ChatError):
    """WebSocket connection failed. Message includes hint to check devserver state."""


class ChatTimeout(ChatError):
    """`until` event did not arrive within timeout."""
    def __init__(self, message: str, *, collected_events: list[dict]) -> None:
        super().__init__(message)
        self.collected_events = collected_events
```

## preflight Integration

Add `LLMApiKeyAvailable` to `testenv/nointern/checks/config.py`:

```python
class LLMApiKeyAvailable(Check):
    """Check existence of LLM vendor API key for chat scenario (WARN)."""

    def __init__(self) -> None:
        super().__init__(
            id="llm-api-key-set",
            name="LLM API key available",
            category="config",
        )

    def run(self, context: RunContext) -> CheckResult:
        for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            if context.env.get(key):
                return CheckResult(status=Status.PASS, message=f"{key} set")
        return CheckResult(
            status=Status.WARN,
            message="no LLM API key set — live chat scenarios will not work",
            fix_hint="export OPENAI_API_KEY=... in testenv/nointern/.env",
        )
```

Register in config section of `all_checks()`. Status.WARN does not block other checks.

## External Dependencies

Use only packages already in existing testenv `pyproject.toml`:

- `nointern-public-client` (editable) — ChatV1Api, SendCodeRequest, etc.
- `nointern-admin-client` (editable) — not directly needed here (auth handled by seed.auth)
- `websockets` — **needs addition**. e2e uses it, so pin same version.

**New addition**: `websockets==16.0` (refer to e2e version).

## Infrastructure Changes

**None**. testenv compose, devserver, preflight unchanged. Add `live/` directory + `websockets` dependency + one preflight WARN check.

## Feasibility Verification Results

Executed immediately after draft. Verified with live ws call against actual devserver.

| # | Item | Result | Note |
|---|---|---|---|
| 1 | `websockets.sync` + ticket flow | ✓ | after `uv add websockets==16.0`, `ws_connect(ws_uri)` succeeds. `chat_v1_issue_ws_ticket` issues ticket when receiving `Authorization: Bearer ...` header |
| 2 | WebSocket handshake `/chat/v1/sessions/{id}?ticket=...` | ✓ | ws connect succeeds, server receives init message and immediately pushes events |
| 3 | Event stream type (dummy key path) | ✓ | observed `run_started → error → run_complete`. Real key expects `run_started → content_delta → text_item → run_complete` |
| 4 | Stage 1c seed flow | ✓ | already verified with Stage 1c result |
| 5 | Image upload/generation endpoint | — | outside this PR stack. Separate feasibility when image phase starts |

### Live Verification Command Log (Reproducible)

```bash
cd testenv/nointern
cp .env.example .env
uv add websockets==16.0
uv run devserver.py up --timeout 120

uv run python <<'PY'
import json, uuid
from seed import auth, workspace, llm, agent
from seed.client import public_client
from nointernpublicclient.api.chat_v1_api import ChatV1Api
from websockets.sync.client import connect as ws_connect

user = auth.create_user()
ws = workspace.create(user)
llm.register_model("gpt-4o-mini")
integration = llm.create_integration(user, ws)   # dummy key
a = agent.create(user, ws, integration, "gpt-4o-mini")

chat_api = ChatV1Api(public_client())
ticket = chat_api.chat_v1_issue_ws_ticket(
    _headers={"Authorization": f"Bearer {user.access_token}"},
).ticket
session_id = uuid.uuid4().hex
uri = f"ws://localhost:8010/chat/v1/sessions/{session_id}?ticket={ticket}"

events = []
with ws_connect(uri) as w:
    w.send(json.dumps({"agent_id": a.id, "message": "Hello"}))
    w.socket.settimeout(20)
    for _ in range(50):
        ev = json.loads(w.recv())
        events.append(ev)
        if ev["type"] in ("run_complete", "run_stopped"):
            break
print([e["type"] for e in events])
# → ['run_started', 'error', 'run_complete']
PY

uv run devserver.py down --all
```

### Meaning in CI (dummy key path)

**Interesting discovery**: pipeline reaches `run_complete` even with dummy key. An `error` event appears in middle, but `run_started` and `run_complete` are normal. This means **even keyless environment can verify Stage 2's "pipeline runs to end"** — but `has_text_content` matcher fails without real key.

Therefore matcher strategy:
- **verification not requiring key**: `matchers.run_completed(events)`, `matchers.ordered(events, ["run_started", "run_complete"])`
- **verification requiring real key**: `matchers.has_text_content(events)` — only on developer machine with real key

### Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `has_text_content` fails in dummy key environment | certain | low | confirmed in feasibility. Document "real key required" in matcher docs. `run_completed`/`ordered` pass even with dummy key |
| `broker/serialization.py` adds new event types | low | low | matchers check only what must exist and ignore unknown types |
| LLM response nondeterminism makes assert flaky | low | medium | do not assert content; only event "type" order. For text_item content, only check "non-empty" |
| WS connect temporarily disconnects in `--reload` mode | low | medium | default is non-reload. Document `--reload` case separately in README |
| matcher misunderstanding when `error` event appears in normal flow | low | low | matchers do not judge existence of `error`; only require reaching `run_complete`. Add `no_error` matcher if needed |

## Implementation Plan

`/ship-feature` stack. Keep phases small.

1. **Phase 1** — dependency + module skeleton
   - add `websockets==16.0` to `pyproject.toml` + pyright include `live`
   - `live/__init__.py`, `live/types.py` (Session), `live/errors.py`
2. **Phase 2** — `live/chat.start_session`
3. **Phase 3** — `live/chat.collect` + `stream` (basic implementation, stream as basis of collect)
4. **Phase 4** — `live/matchers.py` (3 matchers)
5. **Phase 5** — `checks/config.LLMApiKeyAvailable` (preflight WARN)
6. **Phase 6** — `README.md` Live section + scenario live verification
7. **(cleanup)** — remove temporary plan

After text pipeline verification completes, continue with image input/output as separate phases 7~9 (§3.7 option C). Proceed after confirming feasibility after this stack.

## Alternatives Considered

### A. Browser-based verification (Playwright)

**Rejected**: Discussion §2. Separate track in Stage 4. Too heavy for backend PR QA.

### B. Namespace like `seed.chat`

**Rejected**: Discussion §3.1. seed is "create", chat is "try running", so concepts are mixed. `live` is also better for Stage 3 extensibility.

### C. async-only

**Rejected**: Discussion §3.2. Overkill because most agent scripts are sync.

### D. iterator-only

**Rejected**: Discussion §3.3. "Receive all events until run_complete" is default for 90% scenarios, so collect gives shorter code.

### E. weak assert with dummy LLM key

**Rejected**: Discussion §3.5. Essence of Stage 2 is "LLM pipeline runs to end", so without real key it lacks meaning.

### F. Include image in first stack

**Rejected**: Discussion §3.7. Real behavior of image endpoint unconfirmed → run text MVP first and add image phase on top.

## Out of Scope (Stage 3/4)

- Tool execution + Sandbox + MCP toolkit (Stage 3)
- Browser + nointern-web (Stage 4)
- WebSocket concurrency/scale test
- Token refresh (`refresh_token`) flow verification
- Session list/delete/message list API — separate phase when needed

## References

- Parent design: [`local-fullstack-test-env.md`](./local-fullstack-test-env.md)
- Discussion: azents/azents#2378
- Implementation issue: azents/azents#2376
- e2e pattern: `python/apps/nointern-e2e/src/tests/utils.py` (`create_chat_session`)
- Event types: `python/apps/nointern/src/nointern/broker/serialization.py`
- Existing modules: `testenv/nointern/{seed,devserverlib,checks}`
