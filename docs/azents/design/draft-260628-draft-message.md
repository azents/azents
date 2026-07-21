---
title: "Draft Agent Session First Message Creation"
created: 2026-06-28
updated: 2026-06-28
tags: [frontend, backend, chat, session, api, historical-reconstruction]
document_role: primary
document_type: design
snapshot_id: draft-260628
migration_source: "docs/azents/design/draft-agent-session-first-message.md"
historical_reconstruction: true
---

# Draft Agent Session First Message Creation

## Context

Agent-focused chat currently creates a non-primary `AgentSession` as soon as the user clicks the
Agent rail "new session" action. This makes abandoned empty sessions durable, pollutes the session
list, and exposes session-scoped tabs before there is a real conversation.

Target product behavior:

1. Clicking "new session" opens a draft chat surface without creating an `AgentSession` row.
2. The draft surface keeps the Agent top bar so users can open Agent navigation and leave the
draft. Session-scoped Projects and Context tabs remain hidden because there is no session-owned state
yet.
3. Sending the first message creates the session and accepts that message in one backend boundary.
4. The browser URL is replaced with the canonical session URL so refresh resumes the created session.

## Decision

Use a route-level draft state plus a REST create-and-send boundary.

### Frontend route model

Add a draft route:

```text
/w/{handle}/agents/{agent_id}/sessions/new
```

The route is not a real session id. It must not call `getAgentSession`, history, live-state, project,
or context APIs. It renders a draft chat page with the Agent context and a `sessionId = null` input
state, so draft text is stored under the existing per-agent `new` draft key.

When the first message succeeds, the page calls `router.replace` to:

```text
/w/{handle}/agents/{agent_id}/sessions/{created_session_id}
```

The concrete session route then mounts the normal `ChatSessionView`, subscribes to live events, and
loads history/live baseline through the existing resync flow.

### Backend write boundary

Add a REST endpoint for first-message session creation:

```text
POST /chat/v1/agents/{agent_id}/sessions/messages
```

The request body contains `client_request_id`, `message`, and optional `attachments`. The response is
`ChatWriteResponse`, reusing the existing write snapshot shape and returning the created
`session_id`.

The endpoint must create the non-primary team session and enqueue the first user input in one service
operation. The operation reuses the existing policy for new team sessions: ensure the team primary
session and snapshot-copy its registered projects to the new session. The endpoint publishes the
input-buffer live projection and sends a `SessionWakeUp` for the created session.

### Atomicity and idempotency scope

The first implementation keeps the atomic no-empty-session property inside one database transaction
for session creation, project copy, runtime ensure, and input-buffer enqueue. If one of those steps
fails before commit, the new session is not persisted.

Attachment materialization happens after the session id is allocated because ModelFile rows require a
session id. Attachment exchange files are agent-scoped, so draft uploads remain valid before session
creation. If attachment materialization fails unexpectedly, the request fails before enqueue and the
transaction rolls back.

The accepted idempotency scope remains session-bound once the session exists because `InputBuffer`
idempotency is `(session_id, kind, idempotency_key)`. Cross-request deduplication before a session id
exists would require an additional create-request registry keyed by `(agent_id, user_id,
client_request_id)`. That registry is deferred until retry telemetry shows it is needed; the UI
prevents duplicate in-flight sends through the existing write-pending guard.

## Rejected Options

### Client-side two-step create then send

Rejected. Calling `POST /agents/{agent_id}/sessions` and then `POST /sessions/{session_id}/messages`
can still leave an empty session if the second request fails or the browser closes between requests.
It does not solve the product problem.

### WebSocket `/sessions/new` creation

Rejected for the current architecture. WebSocket is now a live subscription and resync transport,
while user writes are REST boundaries that return authoritative snapshots. A REST create-and-send
boundary fits the existing `ChatWriteResponse` and tRPC flow.

### Treat `new` as a fake `session_id`

Rejected. A fake session id would leak into session-scoped APIs and risks accidental persistence or
confusing 404 behavior. Draft state should be explicit route/UI state, not a session identity.

## Test Strategy

### E2E primary verification matrix

Primary product verification belongs in public API and web E2E coverage:

| Scenario | Expected result |
| --- | --- |
| User opens `/sessions/new` | No non-primary `AgentSession` is created; only draft chat UI is shown. |
| User sends first message from draft | API creates a non-primary session, returns `session_id`, and the UI replaces the URL. |
| User refreshes after URL replacement | Concrete session route loads the created session and its pending/live state. |
| User abandons draft page | No empty non-primary session appears in the Agent session list. |
| Primary session has registered projects | Created first-message session receives a project snapshot. |

### E2E plan

- Add public API E2E coverage for `POST /chat/v1/agents/{agent_id}/sessions/messages`:
  - Create agent + primary session fixture.
  - Record session list before first-message creation.
  - Call the first-message endpoint.
  - Assert returned `session_id` is non-primary and appears in the agent session list.
  - Assert the write snapshot contains the first input buffer for the created session.
- Add frontend route/container tests only if the existing frontend test harness already covers Agent
  routes. Otherwise rely on TypeScript typecheck plus manual UI review for the draft route.

### Testenv and fixture requirements

No new testenv fixture support is required. Existing public API fixtures can create a workspace,
agent, auth token, and team primary session. No external LLM credential is required because the test
asserts input-buffer acceptance before model execution.

### Credential and prerequisite snapshot

The E2E API test uses the local Azents E2E substrate and does not need live provider credentials.
The frontend typecheck requires only generated OpenAPI clients.

### Evidence format and CI policy

The PR should include:

- Backend unit tests for the create-and-send service/API boundary.
- Public API E2E test for first-message team session creation.
- TypeScript typecheck for azents-web after generated client updates.
- CI check results from the opened PR.

Optional live/browser verification may be skipped in CI if the repository does not currently run a
browser E2E suite for the Agent route. In that case, the skip reason is that the implemented behavior
is covered at the public API boundary and by TypeScript route compilation.

### Fail and skip criteria

- Fail if clicking new session still calls the create-session API before first message.
- Fail if first-message send can return success without a concrete `session_id`.
- Fail if the concrete session URL is pushed instead of replaced from the draft route.
- Fail if session-scoped Projects or Context tabs render on the draft route.
