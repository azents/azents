---
title: "Runtime Web Heavy Transport Phase 3 Clean Cutover"
created: 2026-09-14
updated: 2026-09-14
tags: [runtime-web, transport, migration, removal, testing]
---

# Runtime Web Heavy Transport Phase 3 Clean Cutover

## Phase Execution Plan

- Phase: `3/4 Clean cutover, removal, and validation substrate`
- Branch/base: `feat/runtime-web-heavy-transport-3-clean-cutover` → `feat/runtime-web-heavy-transport-2-gateway-operations`
- PR boundary: activate the single fingerprint-fenced persistent Runtime Web path, remove the request-scoped transport and all compatibility surfaces, apply the forward-only destructive schema transition, and add deterministic cutover evidence
- Inputs: Phase 1 persistent protocol, fingerprint, capacity, Owner, Runner, and route foundation; Phase 2 Gateway, relay, operations, and Helm primitives; approved Design revision `1`
- Deliverables: production Gateway and Control session lifecycle; exact capability and readiness selection; hard-limit and drain integration; Owner/Runner generation invalidation; maintenance preflight; forward migration; complete old protocol, state, setting, client, channel, test, fixture, and generated-surface removal; deterministic integration, fault, transfer, streaming, relay, capacity, and cutover validation substrate
- Non-goals: no protocol version or fallback; no compatibility alias; no live migration, deployment, restart, Kubernetes write, merge, or operator cutover; no Living Spec promotion or plan cleanup; no threshold waiver or resource inflation
- Interfaces: replacement `RuntimeWebGatewaySession.Connect`, `RuntimeWebControlSession.Relay`, and `RuntimeRunnerWebSession.Connect`; exact `RUNTIME_WEB_PROTOCOL_FINGERPRINT`; full Owner epoch and Runtime generation tuple; M5 absolute credit; M7 backend-neutral capacity; M8 no-resume drain; M10 browser and loopback policy
- Approved Design mechanisms: `M1` through `M15`, with primary phase authority from `M4`, `M8`, `M12`, `M13`, and `M14`
- Authority references: `runtimeweb-260914/REQ-1` through `REQ-14`; ADR-D1 through ADR-D9; approved Design revision `1`; existing Runtime Web policy Specs retained under M10
- Design delta: `None`
- Removal obligations: every row in the Design `Removal and Replacement` table except retained M10 authority; old request-scoped RPCs/messages/intents, tables, admission keys, clients/channels, 64 KiB frame setting, per-endpoint/user/Agent limits, ten-minute SSE deadline, old capability, tests, fixtures, and generated surfaces
- Absence verification: protobuf descriptor and generated API scan; repository symbol and configuration scan; schema metadata and forward-migration assertions; deleted-file inventory; no old capability/fallback import; no active old rows required by the preflight; replacement-only integration tests

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Integrated implementation and correction | `/root` | all Phase 3 protocol, generated, persistence, migration, Gateway, Control, Runner, Helm, and testenv paths | completed implementation handoffs on the rebased stack | coherent replacement-only Phase 3 with no compatibility surface | focused checks followed by root-owned integrated validation |
| Integrated validation | `/root` | complete stable Phase 3 diff and its runtime prerequisites | integrated implementation | bounded local/relay, capacity, Redis fallback, transfer, slow-peer, SSE, WebSocket, fault, maintenance-cutover, migration, and absence evidence | root-executed Python, generated, migration, Helm, testenv, Docker E2E, and repository scans |

- Integration order: destructive protobuf and generated-surface replacement → persistence migration and model/repository removal → Gateway/Control/Runner composition activation → exact capability/readiness and operations lifecycle → Helm lifecycle → deterministic validation substrate → repository-wide absence audit
- Independent review: after all implementation is complete and integrated validation is stable, `/root` requests one review of the complete Phase 3 diff from `/root/runtime-web-heavy-reviewer`; the reviewer checks exact M1-M15 behavior, every M14 removal row, destructive migration safety, exact fingerprint and generation fencing, browser and loopback policy preservation, one-hop maximum, bounded credit/resources, drain/no replay, Redis optionality, content-free evidence, and absence of compatibility or live actions
- Final validation: `/root` runs affected Python Ruff/format/ty/pytest across backend, runtime-control, and Runner; protobuf generation clean diff; migration upgrade and schema assertions; Helm render/lint/schema; deterministic testenv lanes; repository-wide old symbol/settings/table/capability scans; documentation validation; `git diff --check`; pre-commit
- Scope-drift check: replacement activates only after exact readiness; old path is deleted rather than retained behind flags; no alternate version, fallback, replay, durable capacity authority, direct Gateway-to-Runner route, live infrastructure action, or new product/API behavior
- Context checkpoint: record active composition and lifecycle, generated and persistence interfaces, every removed surface and absence proof, one-time heavy-load and recurring lightweight test evidence, remaining Phase 4 stack validation, Spec promotion, and plan cleanup, risks, and `Design delta: None`
