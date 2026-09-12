---
title: "Temporary Runtime Web Services Phase 1 — Authority Foundation"
created: 2026-09-12
tags: [runtime, web, implementation, planning, backend, api]
---

# Phase Execution Plan

- Phase: `1/5 — Authority foundation`
- Branch/base: `feat/runtime-web-gateway-1-authority` → `origin/main`
- PR boundary: Durable service identity and approval contracts that can be exercised without a live Gateway or Runtime.
- Inputs: Approved `web-260912` Requirements, ADR D1–D10 and Design revision 2.
- Deliverables: Additive schema, shared Session access resolver, domain operations/projections, Public API/OpenAPI clients, Runtime-independent Agent tools, immutable Chat result metadata contract, and focused tests.
- Non-goals: Gateway HTTP server, browser cookie exchange, Control/Runner byte relay, Services UI and real proxy E2E.
- Interfaces: The exact endpoint/request/cycle/receipt/config and API/tool semantics in the approved Design. Later phases may add reachability but do not change authority.
- Approved Design mechanisms: `M1, M2, M3` (durable records only), `M4, M5, M12` (logical quota only), `M13, M14` (schema/audit tests).
- Authority references: `web-260912/REQ-1`–`REQ-7`, `REQ-9`, `REQ-12`, `REQ-13`; ADR-D2, D4, D8, D9, D10; approved Design revision 2.
- Design delta: `None`
- Removal obligations: Establish no visibility/extend API, no Runtime-coupled approval and no OAuth approval event. Existing Chat authorization helper is replaced by a shared resolver with identical behavior.
- Absence verification: API/tool schema search, Chat event enum unchanged, Runtime restart fields absent from approval rows, authorization parity tests.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Persistence and domain operations | `authority-backend-owner` | `rdb/models/runtime_web*`, generated migration, `repos/runtime_web/**`, `services/runtime_web/**`, shared Session authority extraction | Design M1–M3/M12/M13 | Transactional durable authority and projection | repository concurrency/service tests; migration validation |
| Public API and Agent tools | `authority-interface-owner` | `api/public/runtime_web/**`, API mount, `engine/tools/runtime_web*`, tool DI/resolve tests | persistence interfaces agreed before edit | Versioned API and nonblocking auto-bound tools | route/data/tool/resolve tests; OpenAPI dump |
| Generated clients and docs integration | root | OpenAPI/client generated surfaces, snapshot docs/plans and integration fixes | both workstreams | Generated contracts and coherent branch | generation diff, docs validators, focused cross-layer tests |

- Integration order: shared typed domain interfaces → models/repository/service → API/tools → migration/OpenAPI/clients → integrated validation.
- Independent review: `gateway-independent-reviewer`; review complete phase diff against `web-260912`, transaction/concurrency/security, generated interfaces, and removal absence. Output is prioritized file/line findings or explicit no-findings.
- Final validation: backend Ruff/format/ty/pytest focused suites; OpenAPI client generation; generated TypeScript typecheck for client; documentation snapshot validation and pre-commit.
- Scope-drift check: All delivered behavior traces to listed mechanisms; no live proxy, UI, new EventKind, mode fallback, extend, visibility or process management.
- Context checkpoint: Phase completes when current Session users/Agents can prepare/request/approve/reject/cancel/close and list durable services through typed services/API/tools, with exact idempotency and active+pending behavior tested. Live reachability remains phases 2–4.
