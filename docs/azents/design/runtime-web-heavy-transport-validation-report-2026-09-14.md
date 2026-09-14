---
title: "Runtime Web Heavy Transport Validation Report"
created: 2026-09-14
tags: [runtime-web, transport, validation, e2e, migration, documentation]
document_role: supporting
document_type: supporting-validation-report
---

# Runtime Web Heavy Transport Validation Report

## Scope

This report records the completed implementation and bounded validation of the
[runtimeweb-260914/REQ](../requirements/runtimeweb-260914-heavy-workload-services.md)
replacement Runtime Web transport under approved
[runtimeweb-260914/ADR](../adr/runtimeweb-260914-heavy-workload-services.md) decisions
and [runtimeweb-260914/DESIGN](runtimeweb-260914-heavy-workload-services.md) revision
`1` mechanisms `M1` through `M15`.

The delivered stack is:

- PR `#1826`, head `f8e62b9908e5bf17860fa2d05b6d0392bbe59621`: inactive
  persistent protocol, Owner, Runner, credit, scheduling, capacity, and generation
  lifecycle foundation;
- PR `#1827`, head `76edbcbca88b7b9d632ed2df8700b6a7463ca16d`: inactive
  Gateway, one-hop relay, operations, Helm foundation, and control/credit boundary
  corrections;
- PR `#1830`, head `ef5a965c1bd211e00ba51f5b74382717755f1d28`:
  replacement activation, destructive migration, legacy removal, independent
  process hard ceilings, typed Runner aggregate telemetry, review corrections, and
  validation substrate; and
- Phase 4 branch `feat/runtime-web-heavy-transport-4-specs-cleanup`: configurable
  low-default E2E workload, Living Spec promotion, validation record, explicit
  outstanding external performance gates, and temporary-plan cleanup.

No PR was merged and no live deployment, Kubernetes write, restart, operator cutover,
or production migration was performed.

## Implemented Behavior

- Gateway, accepting Control, maximum-one-hop Owner relay, and Runner use persistent
  exact-fingerprint sessions with full Owner and Runtime-generation fencing.
- Logical HTTP, SSE, and WebSocket streams preserve raw bytes, independent authority,
  absolute hierarchical credit, bounded queues, fair scheduling, and no-replay
  terminal behavior.
- One exact `runtime_web_session_routes` row owns current Owner discovery and fencing.
  Runtime capacity, stream registries, tombstones, scheduling, and grants remain
  ephemeral with behaviorally equivalent in-memory and Redis implementations.
- Gateway, Control, relay, and Runner apply independent process hard limits.
  Control accounts every managed Runtime Web task before creation and releases it
  exactly once on completion, cancellation, failure, or close. Redis loss is not a
  readiness or correctness dependency.
- Runner telemetry uses the existing generation-fenced `RunnerSystemMetrics` path
  rather than an application port. Control exports the latest active-generation
  snapshots with complete protocol, direction, and close-reason dimensions and the
  worst normalized Runner event-loop lag pressure.
- Planned drain withdraws readiness, rejects post-drain sessions and opens, grants
  bounded finite and long-lived cleanup, and never resumes active work on another
  epoch.
- The old request-scoped protobuf service, Runner intent/client, tunnel and admission
  tables, transport coordinator/dispatcher, old limits and deadlines, generated
  surfaces, tests, fixtures, compatibility aliases, and fallbacks are removed.
- Public Runtime Web endpoint, approval, identity, Session authorization, browser
  policy, numeric loopback, redirect, and content-secrecy behavior are preserved.

## Review Findings and Corrections

The mandatory single reviewer found and verified corrections for the initial
cutover findings and the later M9 completion findings:

1. repeated browser `Sec-WebSocket-Protocol` fields could be validated as an
   aggregate while aiohttp generated the public `101` from only the first field; and
2. Runtime Control could accept a new Gateway source or logical `OPEN` after global
   drain began;
3. an intermediate Runner telemetry implementation occupied application port `8042`
   instead of using the existing Control path;
4. several Control reader, renewal, heartbeat, and relay-monitor tasks were outside
   the configured process-wide task budget;
5. an intermediate fleet projection summed instantaneous event-loop lag and
   accepted incomplete metric dimension sets; and
6. Runner session and active-stream limits were missing from the aggregate snapshot.

The corrections reject repeated fields and duplicate exact tokens before `101`,
cancel and clean the upstream stream, reject post-drain Gateway and relay sessions,
check global drain at `OPEN`, and linearize drain against final binding insertion and
capacity cleanup. Raw TCP and deterministic race regressions cover both boundaries.
The final targeted re-review verified the Control task lifecycle, strict complete
snapshot validation, listener and port-setting absence, worst-process normalized
lag projection, session/stream limit correlation, bounded labels, and no fallback.
It concluded Blocker `0`, Major `0`, Minor `0`, and `Design delta: None`.

## Validation Evidence

| Boundary | Result |
| --- | --- |
| Backend Ruff, format, and full `ty --error-on-warning` | Passed |
| Initial affected backend tests | `191 passed` |
| New Control session server tests before review correction | `15 passed` |
| Post-review correction-owning and adjacent backend tests | `101 passed` |
| Backend full suite after M9 correction | `5,736 passed, 3 skipped` |
| Runtime Control library suite | `271 passed` |
| Runtime Runner suite | `217 passed` |
| Docker Runtime Provider suite | `35 passed` |
| Kubernetes Runtime Provider suite | `180 passed` |
| Alembic migration suite | `14 passed` |
| Helm lint and render suite | lint passed; `88 passed` |
| Protobuf regeneration | Clean diff |
| Documentation, JSON/YAML, lockfile, OpenAPI, and changed-file pre-commit | Passed |
| Legacy protocol/source/config/schema absence scans | Passed |
| One-time bounded heavy real-Runtime run | `1 passed, 3 warnings in 90.22s` |
| Final corrected Phase 3 rebuilt-image lightweight Runtime Web E2E | `4 passed, 6 warnings in 171.59s` |
| Final independent M9 re-review | Blocker `0`, Major `0`, Minor `0`; approved |
| Phase 4 configurable-workload default Runtime Web E2E | `4 passed, 6 warnings in 164.08s` |
| Phase 4 custom workload injection | `2 MiB`, `17` assets, `300s` timeout values reached fixture and browser scripts |
| Runtime Web E2E collection | exactly four tests |

The one-time load execution and its environment, image digests, workload, command,
defects, and limits are recorded in the
[2026-09-14 load-test report](runtime-web-heavy-transport-load-test-report-2026-09-14.md).

## Workload Configuration and CI Policy

The maintained Runtime Web E2E journey uses low recurring defaults:

- transfer bytes: `1 MiB`;
- asset count: `8`; and
- browser script timeout: `120s`.

The same four-test collection accepts bounded
`AZENTS_E2E_RUNTIME_WEB_TRANSFER_BYTES` up to `1 GiB`,
`AZENTS_E2E_RUNTIME_WEB_ASSET_COUNT` up to `2,000`, and
`AZENTS_E2E_RUNTIME_WEB_SCRIPT_TIMEOUT_SECONDS` up to `7,200` seconds. CI does not set
a heavy profile, and there is no separate heavy test node. A future explicitly
requested load run may raise those values once and must record a new dated report.

The scheduled/release benchmark thresholds for 2,000 assets, 1 GiB direct/local/relay
throughput ratios, ten-minute slow-peer behavior, one-hour long-lived traffic,
five-run distributions, and two-to-four Gateway scale are not represented as passed
by the bounded local report. They remain external performance-gate measurements for
a declared reference runner and do not change the implemented transport contract or
the low recurring CI workload.

## Living Spec Impact

Updated current Specs:

- `docs/azents/spec/flow/agent-runtime-control.md` — persistent sessions, logical
  streams, fingerprint and generation fences, credit and scheduling, Runtime
  capacity, drain, readiness, translation, telemetry, and legacy removal;
- `docs/azents/spec/flow/agent-runtime-persistence.md` — exact Owner route lease,
  ephemeral Redis/in-memory capacity, non-persistence, and removed legacy tables; and
- `docs/azents/spec/flow/test-strategy-e2e-primary.md` — four-test low-default matrix,
  bounded workload overrides, and one-time load-report policy.

No material update was required for Agent, Conversation, Toolkit, Agent Execution
Loop, or User Auth Specs because their Runtime Web product authority, tool contract,
content retention, and browser identity behavior did not change.

## Cleanup and Final Assessment

The feature implementation plan and all four phase execution plans are removed after
Spec promotion. The Requirements and Design intentionally remain without an
`implemented` marker because the external REQ-14 performance and scale gates above
are not yet represented as passed. The accepted ADR remains unchanged.

The recurring E2E still emits an existing `StopAsyncIteration` teardown log from the
unchanged Runner Terminal server after successful test completion. The Runtime Web
feature did not modify that file or rely on the warning as success evidence.

All implemented mechanisms and authoritative removals remain within approved Design
revision `1`. No compatibility path, fallback, replay mode, durable capacity
authority, direct Gateway-to-Runner route, or live infrastructure action was added.

**Design delta: None.**
