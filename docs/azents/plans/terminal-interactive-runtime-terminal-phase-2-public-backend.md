---
title: "Interactive Runtime Terminal Phase 2 — Policy, Coordination, and Public Backend"
created: 2026-09-01
updated: 2026-09-01
tags: [terminal, runtime, backend, websocket, policy, implementation]
---

# Interactive Runtime Terminal Phase 2 — Policy, Coordination, and Public Backend

## Phase Execution Plan

- Phase: `2 — Policy, coordination, and Public Terminal backend`
- Branch/base: `feature/terminal-260901-backend` → `feature/terminal-260901`
- PR title: `Runtime Terminal [2/5]: Add policy and public backend`
- PR boundary: Add durable Terminal policy fields, effective policy and Session projection, volatile Terminal coordination, Terminal admission/ticket/WebSocket services, the real Runtime Control Terminal broker, and lifecycle/revocation integration. Keep all Main Web UI, xterm.js, Shell removal, E2E, and Living Spec promotion outside this phase.
- Inputs: Phase 1 commit `71cfefce7` and PR `#1595`; confirmed `terminal-260901/REQ`; accepted `terminal-260901/ADR-D1`–`ADR-D6`; approved `terminal-260901/DESIGN` revision `1`; Phase 1 `terminal.v1`, Control intents, dedicated Terminal RPC, and Runner PTY contracts.
- Deliverables: Three default-true `terminal_enabled` row fields and management API contracts; `TerminalPolicyResolver`; Session Terminal projection and resource-bound one-time ticket; Redis and in-memory `RuntimeTerminalCoordinationStore` parity; bounded replay/input/output/resize/attachment/Runner-stream state; dedicated Public Terminal WebSocket; current Runner broker activation; open/terminate intent dispatch; active policy/access/Runtime invalidation; additive generated clients; deterministic backend tests.
- Non-goals: Main Web Terminal UI, xterm.js dependencies, responsive presentation, `shell_enabled` removal or behavior changes, required product E2E, Living Spec promotion, implementation markers, plan cleanup, live infrastructure mutation, compatibility fallback for old Runners.
- Interfaces: Exact M2 REST/WebSocket paths and frame bounds; M3 coordination state/status taxonomy and quotas; M4 attachment/replay/backpressure; M7 three independent default-true policy sources; M8 stopped/starting/unavailable/ready/active/ended projection with explicit Runtime Start only; Phase 1 `terminal.open.v1`, `terminal.terminate.v1`, `terminal.v1`, `RuntimeRunnerTerminalBroker`, and sequence/generation contracts.
- Approved Design mechanisms: `M1`, `M2`, `M4`, `M7`, `M8`, `M10`, `M12`
- Authority references: `terminal-260901/REQ-1`–`REQ-11`; `terminal-260901/ADR-D1`–`ADR-D6`; current Agent, Workspace, Conversation, Runtime Control, Runtime Persistence, and API Specs; Redis-optional and Runner-reported Workspace conventions.
- Design delta: `None`
- Removal obligations: Terminal frames must remain absent from Chat WebSocket and existing operation/reply byte streams. Terminal policy must remain independent from Worker Runtime Toolkit capability and `shell_enabled` remains authoritative for its existing behavior until Phase 4. No durable Terminal content storage may be introduced.
- Absence verification: Static route/protocol inventory, Chat transport tests, existing operation protocol tests, schema/object-store/log grep, capability resolver tests, and diff inspection prove the prohibited paths remain absent.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Policy schema, persistence, management contracts, and resolver | `/root/terminal-policy-owner` | generated Alembic revision and revision pointer; Agent/runtime-profile RDB models; Agent/runtime-profile repositories, services, Public/Admin API data/routes/tests; new Terminal policy resolver/projection modules | Approved M7/M8 and current profile/Agent services | Three row fields, default/replace/patch behavior, effective denial order, no physical reconciliation for Terminal-only Profile changes | migration upgrade/downgrade/default tests; repository/service/API Ruff, format, ty, pytest; OpenAPI source readiness |
| Volatile Terminal coordination | `/root/terminal-coordination-owner` | new `python/apps/azents/src/azents/runtime/terminal_coordination/**` only | Approved M1/M3/M4/M6/M10 and Phase 1 typed contracts | Protocol, immutable data/status types, in-memory store, Redis store/Lua fencing, shared contract tests, quotas/windows/replay/leases/invalidation indexes | parity contract suite, focused Ruff/format/ty/pytest, Redis-loss/finalization/sequence/backpressure tests |
| Public Terminal service, projection, ticket, and WebSocket | `/root/terminal-api-owner` | new `python/apps/azents/src/azents/services/runtime_terminal/**`; new `python/apps/azents/src/azents/api/public/terminal/**`; focused tests | Policy resolver and coordination Protocol interfaces; existing Session authorization/working-folder/Runtime services | Exact M2 routes, stopped/no-auto-start projection, resource-bound 30-second one-time ticket, dedicated typed WebSocket and binary framing, five-second revalidation | service/API/WebSocket tests, malformed/rate/quota/replay/revocation tests, no Chat changes |
| Runtime Control broker and lifecycle invalidation | `/root` | Phase 1 `runner_terminal_server.py`, `control_server.py`, Runner Control Terminal dispatch integration, Runtime lifecycle/recreation/removal hooks, focused tests | Coordination store and Terminal service interfaces | Real generation-fenced broker, Runner stream attachment, open/terminate intent dispatch, replacement/revocation/Runtime lifecycle invalidation without waiting | backend gRPC/lifecycle tests, exact generation tests, Runtime-priority timing assertions |
| OpenAPI, generated clients, integration, and phase validation | `/root` | OpenAPI dumps and generated Public/Admin Python/TypeScript clients; phase-owned cross-path fixes; plan checkpoint | All workstreams | Stable additive backend contract and complete Phase 2 validation | OpenAPI/client generation, all affected Python/TypeScript checks, static absence inventory |

- Integration order:
  1. Policy and coordination owners define stable typed interfaces and tests in parallel.
  2. Public API owner implements service/projection/ticket/WebSocket against those Protocols without reaching into store internals.
  3. Primary agent activates the Phase 1 Control broker, Terminal intents, and Runtime-priority invalidation against coordination.
  4. Primary agent resolves cross-workstream integration, regenerates OpenAPI clients, runs the full phase matrix, and freezes the diff.
- Independent review: `/root/terminal-reviewer` reviews the stable Phase 2 diff read-only against REQ-1–REQ-11, ADR-D1–D6, Design M1/M2/M3/M4/M6/M7/M8/M10/M12, this plan, authorization, generation/attachment fencing, Redis parity, no-auto-start behavior, content privacy, lifecycle priority, policy/Toolkit separation, migration safety, and prohibited transport absence. Security/data-loss, material interface, Requirements/Design, and convention corrections receive targeted re-review by the same reviewer.
- Final validation:
  - migration generation provenance plus upgrade/downgrade/existing-row default tests;
  - `cd python/apps/azents && uv run ruff check . && uv run ruff format --check . && uv run ty check --error-on-warning && uv run pytest -q` for affected suites, followed by the phase-focused aggregate;
  - `cd python/apps/azents && uv run python src/cli/dump_openapi.py` and repository OpenAPI client generation workflow;
  - affected generated Python client Ruff/format/ty/tests;
  - `cd typescript && pnpm run format && pnpm run lint && pnpm run typecheck` for generated client changes;
  - root `git diff --check`, docs validation through pre-commit, Chat/operation transport absence inventory, durable-content/logging inventory.
- Scope-drift check: Verify every Phase 2 deliverable is present; Public API paths and wire frames match M2; stopped Runtime never auto-starts; coordination is Redis-optional with exact parity; policy is independent of Worker Toolkit and `shell_enabled`; no Main Web/xterm/E2E/Spec-promotion work appears; no Terminal content reaches PostgreSQL, object storage, logs, metrics, traces, Sentry, analytics, Chat, or existing operation byte streams; `Design delta` remains `None`.
- Context checkpoint: Record migration revision and defaults, policy denial taxonomy and source versions, coordination status taxonomy and bounds, REST/WebSocket/OpenAPI versions, ticket binding, broker/invalidation behavior, mixed-Runner failure mode, validation commands/results, reviewer result, remaining Phase 3 interfaces, branch SHA, and PR link.
