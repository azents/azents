---
title: "Runtime HTTP File Download Streaming Phase 1"
created: 2026-09-17
tags: [runtime, files, http, transfer, api, testing]
---
# Phase Execution Plan

- Phase: `1 — Complete HTTP download streaming cutover`
- Branch/base: `feat/runtime-http-download-streaming` → `main`
- PR boundary: Response-scoped Runtime consumer, final-send-aware ASGI adapter,
  Workspace and Exchange HTTP route cutover, deterministic tests, validation, and
  Living Spec promotion.
- Inputs: Confirmed `download-260917/REQ`, accepted `download-260917/ADR`, and approved
  `download-260917/DESIGN` revision `3`.
- Deliverables:
  - Workspace HTTP downloads stream a verified Runtime transfer object without a
    complete API-process body copy.
  - Exchange HTTP downloads stream the authorized original object while non-HTTP
    consumers retain the existing byte contract.
  - Exact EOF and successful final ASGI send form the terminal completion commit.
  - Every earlier failure explicitly closes the producer and performs one bounded
    unsuccessful terminal action.
  - Existing routes, headers, authorities, protocols, and error semantics remain.
- Non-goals: Persistent Runtime Stream Session file messages, typed transfer protocol
  changes, range or resume, replay, database or Helm changes, and live infrastructure
  operations.
- Interfaces: Existing public route paths and response metadata; existing
  Runtime-to-server publication callback behavior; existing Exchange byte-returning
  methods; existing `S3Service.iter_chunks()` ownership contract.
- Approved Design mechanisms: `M1, M2, M3, M4, M5, M6, M7`.
- Authority references: `download-260917/REQ-1` through `REQ-5`;
  `download-260917/ADR-D1` through `ADR-D5`; approved
  `download-260917/DESIGN` revision `3`; current Agent Runtime Control and File Exchange
  and Storage Specs.
- Design delta: `None`
- Removal obligations: Workspace `_BytesCallback` HTTP materialization; Workspace and
  Exchange route `io.BytesIO(...)` wrappers.
- Absence verification: Source search and tests prove `download_bytes()` and
  `io.BytesIO(...)` are absent from the two HTTP paths, while protocol symbol searches
  and regression suites prove no persistent-session file mode or fallback exists.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Runtime consumer lifecycle | root | `python/apps/azents/src/azents/runtime/transfer/runtime_to_server.py` and tests | Existing transfer coordinator | Prepared response consumer preserving publication semantics | Focused Runtime transfer pytest, Ruff, ty |
| Response adapter | root | Public chat API response helper and tests | Runtime consumer terminal contract | EOF/final-send commit, explicit close, exactly-once terminal action | ASGI 2.3/2.4 deterministic tests |
| Workspace stream | root | Workspace service, Runtime workspace download service, tests | Runtime consumer and adapter | Bounded verified Workspace response handle | Workspace service/transfer/API tests |
| Exchange stream | root | Exchange service and tests | Response adapter | Authorized bounded Exchange response handle, preserved byte consumers | Exchange service/API and consumer regressions |
| Product verification | root | Public E2E, relevant Specs, snapshot documents | Integrated implementation | Required E2E evidence and current Living Specs | Required E2E plus snapshot validation |

- Integration order: Runtime consumer lifecycle → source handles → response adapter →
  public routes → focused regressions → quality and E2E → Spec promotion → plan cleanup.
- Independent review: `hardtack` reviews the stable integrated diff after all workstreams
  and root-owned validation complete.
- Final validation: Root runs affected Runtime, Workspace, Exchange, API, Agent input,
  External Channel, and Runtime Stream Session pytest suites; Ruff; format check;
  `ty check --error-on-warning`; documentation validation; required public E2E.
- Scope-drift check: Every diff hunk maps to `M1` through `M7` or required current-Spec
  promotion. Reject new routes, durable state, protocol messages, compatibility paths,
  storage authority, replay, range/resume, or unrelated file-consumer changes.
- Context checkpoint: The phase is complete only when both HTTP routes are bounded,
  final-send completion is sticky, unsuccessful exits clean up exactly once, old HTTP
  buffering is absent, non-HTTP consumers and protocols regress cleanly, Specs match,
  and no approved mechanism is missing.
