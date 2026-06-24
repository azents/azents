---
title: "Slack BYOA Real Implementation Design"
tags: [backend, api, frontend]
created: 2026-04-12
updated: 2026-04-12
implemented: 2026-04-12
---

# Slack BYOA Real Implementation Design

## Overview

End-to-end implementation design for Slack BYOA (Bring Your Own App). Scaffolding (DB model, service, API, frontend) is complete, but this resolves 6 gaps that make it non-functional in practice.

**Problems solved:**
1. Cannot receive BYOA app events (signing secret verification fails).
2. Multiple BYOA installations impossible due to one-installation-per-workspace constraint.
3. No manifest generation function to help create BYOA app.
4. BYOA-only operation impossible without Platform App.

**User scenario:**
1. Agent owner directly creates Slack App (using manifest provided by nointern).
2. Register Bot Token, Signing Secret, App ID in nointern.
3. Configure Event URL provided by nointern in Slack App.
4. Conversation with agent is possible in Slack.

## Discussion Points and Decisions

Details: [`docs/nointern/adr/0026-slack-byoa.md`](../adr/0026-slack-byoa.md)

| # | Point | Decision | Core rationale |
|---|--------|------|-----------|
| 1 | Event Verification | single endpoint + dynamic verification by `api_app_id` | safe to omit signature for `url_verification`; URL can be included in Manifest |
| 2 | DB schema | Multi-installation per workspace (Option A: Platform+BYOA coexist) | allow coexistence in same Slack WS, route with contextvar |
| 3 | Credential storage | Add columns to existing table | same pattern as `agent_id`, separate table unnecessary |
| 4 | Manifest | Slack one-click + JSON download (including Event URL) | URL can be preconfigured because endpoint is single |
| 5 | SlackConfig | Always create Bolt | support BYOA-only operation |
| 6 | Development environment | documentation only | everyday development sufficiently covered by Platform Socket Mode |
| 7 | Frontend form | 3 fields (token, secret, app_id) | auto-fetch team information with `auth.test` |

## Architecture

### Full flow (BYOA)

```mermaid
sequenceDiagram
    participant U as Slack User
    participant S as Slack API
    participant N as nointern API
    participant B as Bolt App
    participant R as Redis Broker
    participant W as EngineWorker

    Note over S,N: single endpoint: /slack/v1/events (shared by Platform + BYOA)

    S->>N: POST /slack/v1/events
    N->>N: parse body → extract api_app_id
    N->>N: lookup BYOA signing_secret from DB (Platform fallback if absent)
    N->>N: HMAC-SHA256 signature verification
    N->>B: delegate to Bolt handler (verification disabled)
    B->>B: _authorize(team_id) → resolve bot_token
    B->>B: handle_message()
    B->>R: broker.send_message(SessionMessage)
    R->>W: process message
    W->>R: publish_event(TextPartial, ...)
    R->>N: subscribe_events
    N->>S: ChatStream.append(text)
```

### Endpoint structure

```
/slack/v1/
├── events                                    ← shared by Platform + BYOA (extend existing endpoint)
├── interactions                              ← shared by Platform + BYOA (extend existing endpoint)
└── oauth-callback                            ← Platform OAuth (existing)

/slack-installation/v1/
├── workspaces/{handle}/
│   ├── slack-installation                    ← single lookup (existing)
│   ├── slack-installations                   ← list lookup (existing, deprecated → change needed)
│   ├── slack-installations/byoa              ← BYOA create (existing → add fields)
│   ├── slack-installations/oauth-url         ← OAuth URL (existing)
│   ├── slack-installations/exchange          ← OAuth exchange (existing)
│   ├── slack-installations/{id}              ← delete (existing)
│   └── agents/{agent_id}/
│       ├── slack-config                      ← per-agent config lookup (new)
│       └── manifest                          ← Manifest generation (new)
```

No new endpoint path added. Only add dynamic verification to existing `/slack/v1/events` and `/slack/v1/interactions`.

### Custom signature verification middleware

```python
# single endpoint: /slack/v1/events (shared by Platform + BYOA)
@router.post("/events")
async def handle_slack_events(request: Request) -> Response:
    raw_body = await request.body()
    body_str = raw_body.decode("utf-8")
    body = json.loads(body_str)

    # 1. url_verification — respond immediately without signature verification
    #    (only returns challenge, no server state change → safe)
    if body.get("type") == "url_verification":
        return Response(content=body.get("challenge", ""), media_type="text/plain")

    # 2. lookup signing secret by api_app_id
    api_app_id = body.get("api_app_id")
    signing_secret = None

    if api_app_id:
        installation = await repo.get_by_slack_app_id(session, api_app_id)
        if installation:
            signing_secret = installation.signing_secret

    # Platform config fallback if not found in BYOA
    if signing_secret is None and config.slack:
        signing_secret = config.slack.signing_secret

    if signing_secret is None:
        return Response(status_code=401)

    # 3. HMAC-SHA256 signature verification
    verifier = SignatureVerifier(signing_secret)
    if not verifier.is_valid_request(body_str, dict(request.headers)):
        return Response(status_code=401)

    # 4. Delegate to Bolt (built-in verification disabled, body safe to re-read via Starlette cache)
    return await bolt_handler.handle(request)
```

### Bolt App change

```python
# before
app = AsyncApp(
    signing_secret=slack_config.signing_secret,
    authorize=_authorize,
)

# after
app = AsyncApp(
    signing_secret="not-used",
    request_verification_enabled=False,  # verified by custom middleware
    authorize=_authorize,
)
```

Change `_authorize` callback to prioritize contextvar.

### contextvar bridge (support multiple installations in same Slack WS)

If Platform + BYOA coexist in same Slack workspace, `team_id` is identical, so `resolve_installation(team_id)` cannot distinguish them. Custom verification middleware already resolved installation by `api_app_id`, so pass that installation through contextvar.

```python
import contextvars

# set in custom middleware, read in handler
_current_installation: contextvars.ContextVar[SlackInstallation | None] = (
    contextvars.ContextVar("_current_installation", default=None)
)

# custom middleware
installation = await repo.get_by_slack_app_id(api_app_id)
_current_installation.set(installation)
await bolt_handler.handle(request)

# _authorize — contextvar first, team_id fallback
async def _authorize(team_id, **kwargs):
    inst = _current_installation.get(None)
    if inst and inst.bot_token:
        return AuthorizeResult(team_id=team_id, bot_token=inst.bot_token)
    # Platform fallback (existing logic)
    installation = await svc.resolve_installation(team_id)
    ...

# _on_message — contextvar first
async def _on_message(body, event):
    inst = _current_installation.get(None)
    if inst is None:
        inst = await svc.resolve_installation(body.get("team_id", ""))
    ...
```

Apply same pattern to every handler (_on_message, _on_nointern_command, _on_agent_select, etc.).

## Data Model

### Schema changes

```mermaid
erDiagram
    workspaces ||--o{ slack_installations : "1:N (changed)"
    agents ||--o{ slack_installations : "BYOA: 1:1"
    agents ||--o{ slack_channel_bindings : "Platform: N:1"
    slack_installations ||--o{ slack_channel_bindings : has
    slack_installations ||--o{ slack_sessions : has
    slack_installations ||--o{ slack_user_links : has

    slack_installations {
        string id PK
        string workspace_id FK "NOT unique (changed)"
        string slack_team_id UK
        string slack_team_name
        string encrypted_bot_token
        string slack_app_id "new, nullable, BYOA only"
        string encrypted_signing_secret "new, nullable, BYOA only"
        enum mode "platform | byoa"
        string agent_id FK "nullable, BYOA only"
        string installed_by
        datetime created_at
        datetime updated_at
    }
```

### Migration changes

```sql
-- 1. remove workspace_id unique
ALTER TABLE slack_installations
    DROP CONSTRAINT uq_slack_installations_workspace_id;

-- 2. remove slack_team_id unique (Platform + BYOA coexist in same Slack WS)
ALTER TABLE slack_installations
    DROP CONSTRAINT uq_slack_installations_slack_team_id;

-- 3. add new columns
ALTER TABLE slack_installations
    ADD COLUMN slack_app_id VARCHAR(32),
    ADD COLUMN encrypted_signing_secret TEXT;

-- 4. slack_app_id unique (partial)
CREATE UNIQUE INDEX uq_slack_installations_slack_app_id
    ON slack_installations (slack_app_id)
    WHERE slack_app_id IS NOT NULL;

-- 5. BYOA: prevent duplicate workspace + agent
CREATE UNIQUE INDEX uq_slack_installations_workspace_agent
    ON slack_installations (workspace_id, agent_id)
    WHERE mode = 'byoa';

-- 6. Platform: keep one per workspace
CREATE UNIQUE INDEX uq_slack_installations_workspace_platform
    ON slack_installations (workspace_id)
    WHERE mode = 'platform';

-- 7. Platform: prevent duplicate slack_team_id (Platform still 1 Slack WS = 1 installation)
CREATE UNIQUE INDEX uq_slack_installations_team_platform
    ON slack_installations (slack_team_id)
    WHERE mode = 'platform';

-- 8. normal workspace_id index (keep existing)
-- ix_slack_installations_workspace_id already exists

-- 9. index for slack_app_id lookup
CREATE INDEX ix_slack_installations_slack_app_id
    ON slack_installations (slack_app_id)
    WHERE slack_app_id IS NOT NULL;
```

### Domain model changes

```python
# repos/slack_installation/data.py
class SlackInstallation(BaseModel):
    # keep existing fields
    id: str
    workspace_id: str
    slack_team_id: str
    slack_team_name: str
    bot_token: str  # decrypted
    mode: SlackInstallationMode
    agent_id: str | None = None
    installed_by: str
    created_at: datetime
    updated_at: datetime
    # new fields
    slack_app_id: str | None = None    # BYOA only
    signing_secret: str | None = None  # BYOA only, decrypted

class SlackInstallationCreate(BaseModel):
    # keep existing fields
    workspace_id: str
    slack_team_id: str
    slack_team_name: str
    bot_token: str
    mode: SlackInstallationMode
    agent_id: str | None = None
    installed_by: str
    # new fields
    slack_app_id: str | None = None
    signing_secret: str | None = None
```

## API Changes

### BYOA installation create (extend existing endpoint)

`POST /slack-installation/v1/workspaces/{handle}/slack-installations/byoa`

**Request Body change:**
```json
{
    "agent_id": "abc123",
    "bot_token": "xoxb-...",
    "signing_secret": "8f742...",
    "slack_app_id": "A06ABCDE12"
}
```

- Remove `slack_team_id`, `slack_team_name` → server automatically looks up via `auth.test` API.
- Add `signing_secret`, `slack_app_id`.

**Response change:**
```json
{
    "id": "inst123",
    "workspace_id": "ws123",
    "slack_team_id": "T06ABCDE12",
    "slack_team_name": "My Team",
    "mode": "byoa",
    "agent_id": "abc123",
    "slack_app_id": "A06ABCDE12",
    "installed_by": "user123",
    "created_at": "2026-04-12T10:00:00Z",
    "updated_at": "2026-04-12T10:00:00Z"
}
```

### Per-agent config lookup (new)

`GET /slack-installation/v1/workspaces/{handle}/agents/{agent_id}/slack-config`

tRPC endpoint called by `getByAgent`. Currently unimplemented → needs implementation.

**Response:**
```json
{
    "id": "inst123",
    "slack_team_id": "T06ABCDE12",
    "slack_team_name": "My Team",
    "mode": "byoa",
    "slack_app_id": "A06ABCDE12"
}
```

### Manifest generation (new)

`GET /slack-installation/v1/workspaces/{handle}/agents/{agent_id}/manifest`

**Response:**
```json
{
    "manifest_json": {
        "_metadata": { "major_version": 1, "minor_version": 1 },
        "display_information": { "name": "Agent Name", "description": "..." },
        "features": { "bot_user": { "display_name": "Agent Name", "always_online": true } },
        "oauth_config": { "scopes": { "bot": ["chat:write", "channels:history", ...] } },
        "settings": {
            "event_subscriptions": {
                "request_url": "https://api.nointern.dev/slack/v1/events",
                "bot_events": ["message.channels", "message.groups", "message.im", "message.mpim"]
            },
            "interactivity": {
                "is_enabled": true,
                "request_url": "https://api.nointern.dev/slack/v1/interactions"
            },
            "socket_mode_enabled": false
        }
    },
    "manifest_url": "https://api.slack.com/apps?new_app=1&manifest_json=..."
}
```

Because endpoint is single, Manifest can include Event URL and Interactions URL. When creating app, Slack automatically sends `url_verification`, and if server responds to challenge, URL verification completes.

## Frontend (UI/UX)

### BYOA setup flow (2-track)

Support both usage paths:
- **Create new app**: create Agent → create Slack app via Manifest → enter Credentials
- **Connect existing app**: directly enter Credentials of already created/installed Slack app (QA, existing app migration, etc.)

```
Agent edit page > Slack section

┌──────────────────────────────────────────┐
│  Slack App connection                     │
│                                           │
│  ┌─────────────────┐ ┌─────────────────┐  │
│  │ Create new app   │ │ Connect existing │ │
│  └─────────────────┘ └─────────────────┘  │
│                                           │
│  [When Create new app selected]           │
│  Step 1: "Create Slack App" button       │
│          (create Slack app via manifest URL) │
│  Step 2: Credential input form (below)    │
│                                           │
│  [When Connect existing app selected]     │
│  Credential input form directly           │
│                                           │
│  ┌──────────────────────────────────┐     │
│  │ App ID        [                ] │     │
│  │ Signing Secret [                ] │     │
│  │ Bot Token      [                ] │     │
│  │                          [Connect]│     │
│  └──────────────────────────────────┘     │
│                                           │
│  After connection:                         │
│  ✅ Connected to "My Team"                │
│  (URL included in Manifest, no extra copy/paste needed) │
│  [Disconnect]                             │
└──────────────────────────────────────────┘
```

Both paths converge to same Credentials form, so backend API is same.

### AgentSlackSection component change

```
Before                           After
─────────                        ─────────
[Bot Token     ]                 [Create new app] | [Connect existing app] tabs
[Slack Team ID ]                 (when new app selected) "Create Slack App" button
[Slack Team Name]                [App ID         ]
[Save]                           [Signing Secret  ]
                                 [Bot Token       ] → auto-detect team
                                 [Connect]

After connected:                 After connected:
"Connected to Team"              "Connected to Team"
[Disconnect]                     [Disconnect]
```

### createByoa mutation change

```typescript
// before
body: {
    agent_id, bot_token, slack_team_id, slack_team_name
}

// after
body: {
    agent_id, bot_token, signing_secret, slack_app_id
}
```

## Infrastructure

No changes.

- BYOA events share existing `/slack/v1/events` endpoint — no new path.
- No separate process, container, or infrastructure change needed.
- No WAF/Load Balancer change needed.

## Feasibility Verification

| Verification item | Status | Result |
|-----------|------|------|
| Bolt `request_verification_enabled=False` | docs checked | officially supported by Bolt, disables `AsyncRequestVerification` middleware |
| custom use of `SignatureVerifier` | docs checked | `slack_sdk.signature.SignatureVerifier` independently usable |
| `url_verification` body structure | docs checked | no `api_app_id` included → per-app endpoint required |
| team info lookup with `auth.test` API | docs checked | returns `team_id`, `team` with bot token |
| Manifest URL app creation | docs checked | `https://api.slack.com/apps?new_app=1&manifest_json=` officially supported |
| Partial unique index (PostgreSQL) | code checked | supports `CREATE UNIQUE INDEX ... WHERE condition` |
| `api_app_id` in Interactions payload | docs checked | form-encoded → included inside JSON payload |
| Starlette body double-read | code checked | `request.body()` caches in `self._body` → safe to re-read in Bolt handler |
| Discord similar pattern | code checked | `verify_gateway_signature` dependency → body reuse pattern already exists |
| slack-bolt version | code checked | 1.27.0 installed, `request_verification_enabled` parameter exists |
| slack-sdk version | code checked | 3.41.0 installed, `SignatureVerifier` class exists |
| SQLAlchemy partial index | code checked | 2.0.44, supports `postgresql_where`. migration possible with `op.execute()` pattern |

### Risks

| Risk | Severity | Mitigation |
|--------|--------|-----------|
| customer impact if BYOA bot token leaks | high | Fernet encrypted storage, TLS transfer, token not included in response |
| existing verification fails if Platform signing_secret changes | medium | Platform endpoint keeps existing method, config reload needed |
| DB lookup performance on massive BYOA installs | low | O(1) lookup with `slack_app_id` unique index |
| Slack API rate limit (`auth.test` call) | low | called only once on installation, DB used afterward |

## testenv QA Scenarios

### 1. BYOA installation + event receive

```python
# seed
user = seed.auth.create_user()
ws = seed.workspace.create(user)
agent = seed.agent.create(ws)

# create BYOA installation (API call)
installation = api.post(f"/slack-installation/v1/workspaces/{ws.handle}/slack-installations/byoa", {
    "agent_id": agent.id,
    "bot_token": "xoxb-test-token",
    "signing_secret": "test-signing-secret-32chars000000",
    "slack_app_id": "A_TEST_APP",
})

# confirm slack_app_id included in response
assert installation["slack_app_id"] == "A_TEST_APP"
```

### 2. Signature verification success/failure

```python
import hmac, hashlib, time, json

# send event with valid signature
timestamp = str(int(time.time()))
body = json.dumps({"type": "event_callback", "team_id": "T_TEST", "event": {...}})
sig_basestring = f"v0:{timestamp}:{body}"
signature = "v0=" + hmac.new(b"test-signing-secret-32chars000000", sig_basestring.encode(), hashlib.sha256).hexdigest()

response = api.post(
    "/slack/v1/events",
    body,
    headers={"X-Slack-Signature": signature, "X-Slack-Request-Timestamp": timestamp}
)
assert response.status_code == 200

# invalid signature → 401
response = api.post(
    "/slack/v1/apps/A_TEST_APP/events",
    body,
    headers={"X-Slack-Signature": "v0=invalid", "X-Slack-Request-Timestamp": timestamp}
)
assert response.status_code == 401
```

### 3. Platform + BYOA coexist

```python
# Platform installation
platform_installation = api.post(f"/slack-installation/v1/.../exchange", {...})

# BYOA installation (same workspace)
byoa_installation = api.post(f"/slack-installation/v1/.../byoa", {
    "agent_id": agent.id, ...
})

# both exist
installations = api.get(f"/slack-installation/v1/.../slack-installations")
assert len(installations["items"]) == 2
```

### 4. url_verification

```python
# url_verification event (with correct signature)
body = json.dumps({"type": "url_verification", "challenge": "test-challenge-123", "token": "..."})
# signature generation (same pattern as above)

response = api.post("/slack/v1/events", body, headers={...})
assert response.status_code == 200
assert response.text == "test-challenge-123"
```

## testenv Impact

| Item | Impact |
|------|------|
| new seed block | `seed.slack.create_byoa_installation(agent, bot_token, signing_secret, slack_app_id)` |
| existing scenarios | Platform App scenarios unaffected (endpoint unchanged) |
| docker-compose | no change |
| .env.example | no change (Platform env vars become optional) |
| preflight checks | no change |

## Implementation Plan

### Phase 1: DB + Backend foundation (core)

1. DB migration: add columns, change unique constraints.
2. Change `RDBSlackInstallation` model + Repository.
3. Change `SlackInstallation` / `SlackInstallationCreate` domain model.
4. Change `SlackInstallationService.create_byoa()`: automatic `auth.test` lookup, save new fields.
5. Bolt app: `request_verification_enabled=False`, remove SlackConfig dependency.
6. Add dynamic signature verification to existing `/slack/v1/events`, `/interactions` endpoints.
7. `api_app_id` → DB lookup (BYOA) → Platform fallback logic.
8. Implement `get_by_agent` API endpoint.
9. Manifest generation API endpoint.

### Phase 2: Frontend changes

1. Improve `AgentSlackSection.tsx` form: 3 fields (token, secret, app_id).
2. Change tRPC `createByoa` mutation.
3. Display Event URL / Interactions URL after installation.
4. Manifest download + "Create in Slack" button.
5. Add i18n translations.

### Phase 3: Platform verification integration

1. Switch Platform endpoint to custom signature verification too (consistency).
2. `_get_bolt_handler` → create Bolt handler even without SlackConfig.
3. Integration tests.

### Phase 4: testenv + docs

1. Implement BYOA seed block.
2. Add testenv scenarios.
3. Development environment guide document.

## Alternatives Considered

| Alternative | Rejection reason |
|------|-----------|
| Per-app endpoint (`/slack/v1/apps/{id}/events`) | Cannot include URL in Manifest, adds user URL copy/paste step, inconvenient QA flow |
| Multiple Bolt instances | memory grows proportionally, duplicate handler registration |
| Keep workspace_id unique | original design "1 Agent = 1 App" impossible |
| separate `slack_byoa_configs` table | excessive normalization, JOIN complexity |
| BYOA also requires Platform credentials | unreasonable constraint |
| Socket Mode for BYOA development | customer would need to provide xapp token, unrealistic |
| built-in ngrok | environment dependent, too complex relative to development frequency |
