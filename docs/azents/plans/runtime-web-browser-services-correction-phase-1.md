---
title: "Runtime Web Browser and Services Correction Phase 1"
created: 2026-09-13
updated: 2026-09-13
tags: [runtime, web, security, frontend, testing]
---

# Runtime Web Browser and Services Correction Phase 1

## Phase Execution Plan

- Phase: `1/1 Browser-neutral authentication and Services completion`
- Branch/base: `feat/runtime-web-cross-browser-services-ui` → `origin/main`
- PR boundary: one synchronized correction of Runtime Web identity and Services UI
- Inputs: confirmed `runtimeweb-260913/REQ`, accepted `runtimeweb-260913/ADR`, approved `runtimeweb-260913/DESIGN`, current Runtime Web and Chat Specs
- Deliverables: browser-neutral Runtime Web authentication, removed browser-profile surfaces, reachable and correct Services management UI, generated contracts, migration, Specs, and regression evidence
- Non-goals: new authentication modes, application health probing, exposure duration extension, visibility controls, process management, compatibility fallback, live deployment, or merge
- Interfaces: the existing opaque identity secret, exact raw Cookie cardinality, Session/approval/Origin/CORS/transport authority, current service projection, revision-fenced mutations, and Runtime Control protocol remain fixed
- Approved Design mechanisms: `M1, M2, M3, M4, M5, M6, M7`
- Authority references: `runtimeweb-260913/REQ-1` through `REQ-6`; `runtimeweb-260913/ADR-D1` through `ADR-D5`; current `agent-runtime-control`, `chat-session-resync`, and `user-auth` Specs; project generated-client and migration constraints
- Design delta: `None`
- Removal obligations: Chromium/version/client-hint admission; browser-profile persistence/API/configuration; capability-probe and browser-proof cookies/routes; disconnected Services navigation; premature confirmation dismissal; inaccurate application-port failure copy
- Absence verification: repository-wide symbol/config/route search, schema migration assertion, OpenAPI/generated client diff, browser-neutral Gateway tests, and desktop/mobile Services navigation tests

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Gateway policy and server | `/root` | `python/apps/azents/src/azents/runtime_web_gateway/**` | approved M1, M2, M6 | browser-neutral HTTP/WebSocket admission using one raw identity cookie | focused policy/server tests |
| Identity persistence and authority | `/root` | Runtime Web model, repository, service, API, Alembic schema | Gateway contract | profile-free opaque identity authority | repository/service/API/migration tests |
| Contracts and deployment configuration | `/root` | Public OpenAPI/generated clients, Helm values/templates/schema | backend API and settings | profile-free generated and deployment surfaces | generation diff, typecheck, chart checks |
| Main Web authentication | `/root` | Runtime Web auth routes/components/helpers/tests | generated Public client | identity establishment without probe/profile | route/component tests |
| Services UI integration | `/root` | Chat panel navigation/container, RuntimeServicesPanel, locales, stories/tests | current service projection | desktop/mobile reachability, URL restoration, success-owned dialogs, honest state | unit/component/story/E2E assertions |
| Specs and E2E | `/root` | affected Living Specs and Runtime Web E2E | stable integrated behavior | current behavior and regression evidence | spec review and E2E |

- Integration order: Gateway/persistence/API → generated clients/config → Main Web auth → Services navigation/interactions → tests/E2E/Specs → review and final validation
- Independent review: `/root/phase1-readonly-review`; read-only review of the stable diff against Requirements, ADR, Design Authority, removal table, phase contract, security/data-loss risks, generated surfaces, and desktop/mobile behavior; output is a bounded finding list with file/line evidence
- Final validation: targeted Python tests; migration tests; Public OpenAPI dump and client generation checks; Python ruff/format/typecheck; targeted TypeScript tests; TypeScript format/lint/typecheck/build; Helm validation; focused Runtime Web E2E; spec review; repository-wide absence searches
- Scope-drift check: every `REQ-1`–`REQ-6` and `M1`–`M7` must have implementation or evidence; no new product action, state, compatibility fallback, authentication mode, probe, health check, or process-control behavior may appear
- Context checkpoint: authority and plans are complete; implementation is unstarted; existing `_exact_cookie`, Services panel/API/state stories, Session navigation, auth profile pipeline, current migration head, and affected Specs are the primary paths; largest risks are incomplete profile removal, WebSocket regression, generated-client drift, and hidden mobile navigation behavior
