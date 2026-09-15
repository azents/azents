---
title: "Runtime Web Heavy Transport Phase 1 Core Transport"
created: 2026-09-14
updated: 2026-09-14
tags: [runtime-web, transport, protocol, runner, implementation]
---

# Runtime Web Heavy Transport Phase 1 Core Transport

## Phase Execution Plan

- Phase: `1/4 Core transport`
- Branch/base: `feat/runtime-web-heavy-transport-1-foundation` → `origin/main`
- PR boundary: approved snapshot documents plus inactive replacement protocol,
  capacity, Owner route, and Runner persistent-session implementation
- Inputs: confirmed `runtimeweb-260914/REQ`, accepted ADR-D1 through ADR-D9,
  approved `runtimeweb-260914/DESIGN` revision `1`
- Deliverables: generated replacement session protobuf; typed shared Python contract;
  deterministic session/stream validation; absolute credit arithmetic; bounded fair
  scheduler; Redis/in-memory capacity coordinator; additive Owner-session route;
  Owner lease/session manager; Runner session offer and persistent Web session;
  generation-scoped pooled loopback HTTP client; coalesced authority watcher building
  blocks
- Non-goals: no Gateway browser wiring; no accepting-Control relay production wiring;
  no capability advertisement; no replacement readiness; no old transport removal;
  no destructive migration; no metrics or Helm activation
- Interfaces: M1/M2 Owner and Runner session, M3/M4 typed frame and fingerprint,
  M5 credit/scheduler, M6 numeric profile, M7 capacity coordinator, M8 lifecycle,
  M10 security boundaries, M11 pooled loopback, M15 authority grouping
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`, `M6`, `M7`, `M8`,
  `M10`, `M11`, `M15`
- Authority references: `runtimeweb-260914/REQ-1` through `REQ-11`, `REQ-13`,
  `REQ-14`; ADR-D1 through ADR-D8; approved Design revision `1`
- Design delta: `None`
- Removal obligations: None in this inactive phase; M14 removals remain owned by
  phase 3
- Absence verification: current Gateway, Control, and Runner production composition
  keeps the old sole active capability and path; replacement session modules remain
  unimported from production entry points

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Approved docs and plans | `/root` | `docs/azents/requirements/runtimeweb-260914-*`, `docs/azents/adr/runtimeweb-260914-*`, `docs/azents/design/runtimeweb-260914-*`, `docs/azents/plans/runtime-web-heavy-transport-*` | approved Design | implementation authority and 4-phase scope | documentation validation, traceability, diff check |
| Protocol/fingerprint/flow/capacity | `/root/runtime-web-protocol-owner` | `proto/azents/runtime_control/v1/runtime_web_session.proto`, `python/libs/azents-runtime-control/` generated surfaces, new session/flow/capacity modules and focused tests | M3-M7 | inactive protocol foundation and full Redis/in-memory parity | proto generation, ruff, typecheck, focused/full pytest, Docker Redis integration |
| Owner route and session | `/root/runtime-web-owner-runner-owner` | new migration; `python/apps/azents/src/azents/rdb/models/runtime_web.py`; `python/apps/azents/src/azents/repos/runtime_web/`; new Owner session modules under Runtime Control and focused tests | protocol foundation, M2 | one-per-Runtime additive session route and inactive Owner manager | migration/model/repository/session tests, Python quality checks |
| Runner persistent data path | `/root/runtime-web-owner-runner-owner` | `python/apps/azents-runtime-runner/src/azents_runtime_runner/` new inactive session/pooled-loopback modules and focused tests; necessary runner client surface in shared library not owned by protocol owner | Owner interface, M1/M8/M10/M11 | persistent Runner session and pooled loopback implementation not activated by runner main | runner ruff/typecheck/pytest, generation invalidation and loopback policy tests |
| Integration and review fixes | `/root` | phase-owned paths only | all workstreams | coherent inactive core | cross-project tests and reviewer disposition |

- Integration order: protocol/fingerprint → state/credit/scheduler → capacity parity →
  Owner route/repository → Owner manager/session offer → Runner session/loopback pool
  → production-import absence check → independent review
- Independent review: `/root/runtime-web-heavy-reviewer` reviews stable checkpoints
  and final phase diff read-only against Requirements, ADR-D1 through D8,
  M1/M2/M3/M4/M5/M6/M7/M8/M10/M11/M15, no-compatibility rule, exact Owner/generation
  matching, hard bounds, Redis parity, Runner loopback security, and deterministic
  tests; prioritized findings go to `/root`
- Final validation: generate protobuf; run ruff, format check, typecheck, and full
  pytest in `azents-runtime-control`, backend app, and Runtime Runner; run actual Redis
  parity integration; validate additive migration; run docs validation; prove no
  production replacement import/capability/readiness activation
- Scope-drift check: replacement remains inactive; no version list, fallback,
  compatibility adapter, persistent capacity state, direct Gateway-to-Runner path,
  application persistence, changed current behavior, or old removal
- Context checkpoint: record interfaces, migrations, tested invariants, reviewer
  result, commands, remaining phase-2 inputs, empirical risks, and `Design delta: None`

## Completed Checkpoint

- Protocol fingerprint: `daae0e1009d1a546ed8e1b55166a83ccd64bc47b074a103240264f2b4e90c1e2`
- Added inactive persistent-session protobuf, strict typed state, absolute credit,
  bounded fair scheduling, and Redis/in-memory capacity parity.
- Added additive `eebc06bf6bf0` migration and one-per-Runtime session route,
  exact Owner lease/session/offer lifecycle, persistent Runner client, generation and
  offer replay fencing, and pooled raw-byte HTTP plus wsproto WebSocket loopback.
- Exact encoded target and obs-text request/response header bytes are preserved.
- Current production Gateway, Control, Runner composition, capability, and old
  transport remain unchanged and sole-active.
- Validation: shared library `208 passed`; Runtime Runner `254 passed`; backend
  Owner/repository/model/migration bounded suite `32 passed`; Ruff and `ty` passed in
  all affected subprojects; actual Redis 7.4 integration passed; production import
  and capability activation scan returned no matches.
- Independent review: `/root/runtime-web-heavy-reviewer` final result `PASS`, blocker
  `0`, major `0`, minor `0`.
- Design delta: `None`.
- Remaining scope: Phase 2 Gateway, relay, capacity wiring, metrics, probes, scaling,
  drain, and Ingress; no Phase 3 removal was started.
