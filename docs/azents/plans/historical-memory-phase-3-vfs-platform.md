---
title: "Historical Memory Phase 3: Pluggable VFS Read Platform"
created: 2026-10-01
updated: 2026-10-01
tags: [memory, vfs, engine, toolkit, runtime, testing]
---

# Historical Memory Phase 3: Pluggable VFS Read Platform

## Phase Execution Plan

- Phase: `3/6 — Pluggable VFS read platform`
- Branch/base: `feature/historical-memory-3-vfs-platform` → `feature/historical-memory-2-preparation`
- PR boundary: replace Runtime-owned generic read tools with one Runtime-independent readable-storage Toolkit and a registered VFS read router, while preserving Runtime path behavior and immutable Skills projection authority
- Inputs: Phase 2 PR #2026 and commit `b7143f2d5`; confirmed `memory-260930/REQ`; accepted `memory-260930/ADR-D12` through `ADR-D14`; approved `memory-260930/DESIGN` revision `1`
- Deliverables: canonical exact/directory/glob validation; server-created `VfsReadContext`; backend capability and result contracts; duplicate-fatal mount registry; bounded read router; immutable Skills backend with read/grep/glob conformance; capability-gated Runtime path adapter; auto-bound readable-storage Toolkit exposing exactly one `read`, `grep`, and `glob` with or without Runtime; optional transfer-read interface without changing current import authority
- Non-goals: live `azents://memory` backend or namespace, Saved/Historical/source rendering, Memory/history tool removal, Historical settings API/UI, generated clients, E2E/load validation, Living Spec promotion, Scheduler rollout, deployment, merge, or compatibility aliases
- Interfaces: `VfsReadContext`; exact/directory/glob location parsers; `VfsReadBackend` capability contract; `VfsReadBackendRegistry`; normalized `TextReadResult`, `GrepResult`, and sorted canonical-URI `VfsGlobResult`; VFS router operations; Skills projection backend; Runtime FileStorage adapter; readable-storage Toolkit/provider auto-binding and execution-owner binding
- Approved Design mechanisms: `M9`, `M11`, `M14`
- Authority references: `memory-260930/REQ-1`, `REQ-2`, `REQ-6`, `REQ-7`, `REQ-8`; `memory-260930/ADR-D5`, `ADR-D12`, `ADR-D13`, `ADR-D14`; current Agent Execution Loop and File Exchange Storage Specs; Runtime capability and execution-owner project constraints
- Design delta: `None`
- Removal obligations: remove `read`, `grep`, and `glob` ownership from `RuntimeToolkit` only after the readable-storage Toolkit passes equivalent Runtime-path behavior tests; replace generic read routing through `AZENTS_VFS_SUPPORTED_MOUNTS` with registry lookup; replace Skills-only exact generic reads with a Skills backend adapter while retaining immutable projection hashes, source revisions, import transfer behavior, and current projection persistence
- Absence verification: tool catalog exposes exactly one unprefixed `read`, `grep`, and `glob` when Runtime is available and unavailable; RuntimeToolkit factories and prompt no longer own those names; generic VFS router contains no static supported-mount allowlist branch; no Memory mount/backend, dedicated Memory/history tool removal, API/UI, generated-client, or Spec change appears in the diff

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Phase contract | `/root` | `docs/azents/plans/historical-memory-phase-3-vfs-platform.md` | Phase 2 checkpoint | Current Phase 3 scope, interfaces, removals, validation, and drift boundary | Docs validation, diff check |
| VFS contracts and registry | `/root` | `python/apps/azents/src/azents/core/vfs.py`, new/read-platform service modules, focused tests | Existing canonical URI and immutable projection models | Exact/directory/glob parsing, read context, backend capabilities, normalized results, duplicate-fatal registry, explicit unsupported-operation errors | URI/parser/property tests, registry collision tests, backend conformance suite |
| Skills backend | `/root` | `python/apps/azents/src/azents/services/vfs.py`, new Skills backend adapter, focused tests | Persisted AgentRun projection and `VfsProjectionService` | Bounded exact text, regex grep, and glob over the immutable at-most-8-MiB projection without changing hashes or source revisions | Existing projection tests plus backend conformance, limits, encoding, integrity, sorted-output tests |
| Runtime adapter and generic tools | `/root` | `python/apps/azents/src/azents/engine/tools/{builtin.py,read_text.py,grep.py,glob.py,runtime_io.py}`, new readable-storage Toolkit/router adapter modules, focused tests | Runtime FileStorage and Runtime capability resolver | Absolute POSIX paths lazily use the Runtime adapter; canonical `azents://` paths use the VFS router; other locations fail explicitly; one stable tool schema per operation | Runtime available/unavailable parity, capability-denied, cancellation/deadline, schema/catalog, duplicate-name tests |
| Composition and execution authority | `/root` | `python/apps/azents/src/azents/engine/{run/resolve.py,tools/deps.py}`, `python/apps/azents/src/azents/worker/{deps.py,run/executor.py}` where required, focused tests | Existing auto-bound Toolkit resolution and owner fencing | Readable-storage Toolkit is present for root/subagent execution independently of Runtime and receives current Run/Session/Agent/Workspace/owner authority | Resolver/composition tests with and without Runtime, owner-generation tests, subagent parity |
| Removal and regression | `/root` | affected tool prompts/catalog snapshots and tests | All replacement workstreams | RuntimeToolkit read/glob/grep removal, registry-based mount routing, unchanged write/delete/edit/patch/process/import/present behavior | Source absence searches, full backend tests, OpenAPI no-diff, projection/import regression tests |

- Integration order: phase plan → VFS contracts/validators/registry → Skills backend and conformance suite → Runtime adapter → readable-storage tool handlers/provider → auto-binding/owner authority → RuntimeToolkit removal and prompt/catalog updates → absence checks → integrated validation
- Independent review: `/root/historical-memory-reviewer`; `/root` requests review only after every Phase 3 workstream is integrated, removal obligations are complete, the diff is stable, and root validation passes
- Final validation: root runs docs validation and `git diff --check`; backend Ruff/format and whole-subproject typecheck; focused VFS core/service/backend, read/grep/glob, RuntimeToolkit, resolver, worker composition, import/Skill projection, owner-generation, and catalog tests; full backend pytest; OpenAPI no-diff; source searches proving one declaration of each generic read tool and no generic resolver dependency on the static mount set
- Scope-drift check: implement only `M9/M11/M14`; keep `Design delta: None`; preserve existing Runtime path semantics, projection persistence/hashes, Skills import authority, Saved/Historical behavior, and all mutation/process tools; omit the Memory backend/tree, dedicated read-tool cutover, settings/UI, Specs, rollout, compatibility aliases, and fallback routing
- Context checkpoint: Phase 2 PR #2026 supplies reviewed Historical preparation and boundary snapshots; Phase 3 freezes the router/backend/toolkit contracts consumed by Phase 4; Phase 4 owns the live Memory backend/tree and six-tool removal; Phase 5 owns settings; Phase 6 owns E2E/load/Specs/implemented markers/plan cleanup; conditional risks are Runtime-independent tool composition, exact Runtime parity, bounded in-memory Skills search, and execution-owner propagation
