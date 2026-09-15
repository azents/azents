---
title: "Runtime Web Heavy Transport Phase 2 Gateway Relay and Operations"
created: 2026-09-14
updated: 2026-09-14
tags: [runtime-web, gateway, transport, observability, infra, implementation]
---

# Runtime Web Heavy Transport Phase 2 Gateway Relay and Operations

## Phase Execution Plan

- Phase: `2/4 Gateway, relay, and operations`
- Branch/base: `feat/runtime-web-heavy-transport-2-gateway-operations` → `feat/runtime-web-heavy-transport-1-foundation`
- PR boundary: inactive Gateway/Control/relay replacement path plus complete operational building blocks
- Inputs: completed Phase 1 core transport and approved Design revision `1`
- Deliverables: Gateway persistent Control-session pool; browser logical-stream bridge; accepting-Control broker; persistent one-hop Owner relay; Owner capacity admission and authority watcher integration; OpenMetrics and Runner telemetry; hard process ceilings; readiness/liveness; HPA pressure; drain/preStop/PDB/Ingress settings
- Non-goals: no replacement capability/readiness activation; no destructive migration; no old transport removal; no live infrastructure change; no protocol/version/fallback change
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M5`, `M7`, `M8`, `M9`, `M10`, `M11`, `M12`, `M15`
- Authority references: `runtimeweb-260914/REQ-1` through `REQ-12`, `REQ-14`; ADR-D1 through ADR-D7 and ADR-D9; approved Design revision `1`
- Design delta: `None`
- Removal obligations: None; all M14 removal stays in Phase 3
- Absence verification: current old Runtime Web composition and capability remain sole-active; replacement modules are not selected by production readiness

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Gateway and relay | `/root/runtime-web-gateway-relay-owner` | new Gateway session/pool/bridge modules and tests; new accepting-Control/relay/broker modules and tests; no Helm or production composition | Phase 1 protocol/Owner | inactive end-to-end logical-stream path with one relay and exact policy/authority | focused ruff/ty/pytest, raw byte, flow, failure, production absence |
| Operations and scaling | `/root/runtime-web-operations-owner` | new metrics/probe/drain helpers; Gateway/Control settings additions; Helm templates/values/tests for HPA, metrics, PDB, preStop, 150-second grace, Ingress contract; no transport modules | M8/M9 | inactive operational contract ready for Phase 3 activation | Python checks, Helm render/tests, bounded-label assertions |
| Integration | `/root` | composition-neutral adapters and phase-owned conflicts only | both workstreams | coherent inactive Phase 2 | cross-project checks and exact reviewer review |

- Integration order: Gateway session pool → Control broker/relay → capacity/authority bridge → operational primitives → chart contract → production activation absence check
- Independent review: `/root/runtime-web-heavy-reviewer` reviews exact D1-D9/M1-M15 boundaries, one-hop relay, browser policy, no replay, bounded buffers, content-free telemetry, Redis availability, probe/HPA semantics, and no active compatibility path
- Final validation: affected Python ruff/format/ty/pytest; Helm render and chart tests; production import/readiness/capability absence; docs validation; `git diff --check`
- Scope-drift check: no activation, old removal, live cluster action, protocol version, fallback, mandatory monitoring stack, Redis correctness dependency, or new product behavior
- Context checkpoint: interfaces, tests, review, remaining Phase 3 activation/removal inputs, Design delta `None`

## Completion Checkpoint

- Completed Gateway path: bounded authenticated session pool; raw-byte-preserving HTTP and WebSocket bridge; hierarchical stream and shared-session absolute credit; browser-consumption `WINDOW_UPDATE`; cancellation, terminal-event, and session-failure cleanup without replay
- Completed Control path: composite source-session admission identity; exact generation and Owner epoch fencing; pending-capacity rollback; monotonic one-hop relay stream remapping; bounded queues, envelopes, tombstones, and connection retirement
- Completed operations path: inactive authority and exact-fingerprint readiness evidence; Redis-independent health; hard resource ceilings and pressure projection; bounded drain coordinator; content-free OpenMetrics; CPU and memory HPA with optional fixed pressure metric; PDB, Ingress, and 150-second termination contract
- Production boundary: the existing request-scoped Runtime Web composition remains unchanged; replacement modules, lifecycle, readiness, drain, and capability selection remain inactive until Phase 3
- Independent review: Gateway and relay `0 blocker / 0 major / 0 minor`; operations and Helm `0 blocker / 0 major / 0 minor`
- Integrated validation: Python Ruff format and lint passed; full application `ty --error-on-warning` passed; Gateway, broker, and relay tests `82 passed`; Helm render tests `12 passed`; Helm lint passed; JSON Schema parse passed; production-reference absence and `git diff --check` passed
- Remaining Phase 3 inputs: activate the exact-fingerprint replacement lifecycle, connect hard limits and drain to the selected bridge, remove the old request-scoped transport, and add clean-cutover validation substrate
- Design delta: `None`
