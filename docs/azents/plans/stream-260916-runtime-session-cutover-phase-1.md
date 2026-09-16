---
title: "Runtime Stream Session Naming Cutover Phase 1"
created: 2026-09-16
updated: 2026-09-16
tags: [runtime, transport, architecture]
---

## Phase Execution Plan

- Phase: `1/1 — atomic naming cutover`
- Branch/base: `refactor/runtime-stream-session-cutover` → current base branch
- PR boundary: one independent PR containing the complete protocol and transport rename
- Inputs: `stream-260916/REQ`, `stream-260916/ADR`, `stream-260916/DESIGN` revision 1
- Deliverables: regenerated stream-neutral protobuf surface, renamed reusable transport
  implementation and consumers, preserved Runtime Web adapters, tests and absence evidence
- Non-goals: file streaming, public API changes, route-table migration, ordinary Runtime
  operations, Terminal, live infrastructure mutation
- Interfaces: existing field numbers/shapes, HTTP/WebSocket enum values, exact fingerprint
  equality, existing Owner epoch and one-hop relay contracts
- Approved Design mechanisms: `M1, M2, M3, M4, M5, M6`
- Authority references: `stream-260916/REQ-1..REQ-4`, `stream-260916/ADR-D1..D3`,
  `stream-260916/DESIGN-M1..M6`, current Agent Runtime Control specs
- Design delta: `None`
- Removal obligations: old Runtime Web Session protobuf/generated names, reusable transport
  module/class names, old fingerprint constant and compatibility paths
- Absence verification: descriptor inspection, active-source `git grep`, import compilation,
  and focused tests asserting renamed services/constants

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Protocol source and generated surface | primary agent | `proto/azents/runtime_control/v1/runtime_stream_session.proto`, `python/libs/azents-runtime-control/src/azents_runtime_control/proto/runtime_stream_session_pb2*` | none | stream-neutral descriptor and stubs | generator plus descriptor assertions |
| Shared transport and session manager | primary agent | `python/libs/azents-runtime-control/src/azents_runtime_control/runtime_stream_*`, `grpc_runner_stream_session_client.py`, `python/apps/azents-runtime-runner/src/azents_runtime_runner/stream_session.py` | generated surface | renamed reusable classes/imports/fingerprint | shared and Runner tests |
| Control/Gateway/Runner consumers | primary agent | `python/apps/azents/src/azents/runtime/**`, `runtime_web_gateway/**`, `control_server.py`, Runner Control wiring | shared transport | complete composition cutover with Web adapter boundary | Control/Gateway/relay/composition tests |
| Tests and absence evidence | primary agent | moved tests and affected package tests | all implementation workstreams | regression assertions and scans | pytest, Ruff, ty, pre-commit |

- Integration order: protocol source → generated bindings → shared transport → Control,
  Gateway, Runner consumers → tests and scans → integrated validation
- Independent review: one read-only reviewer reviews the frozen integrated diff after all
  workstreams and validation are complete
- Final validation: primary agent runs generator check, targeted pytest, Ruff/format, ty,
  docs/pre-commit checks, descriptor/fingerprint assertions, and repository-wide scans
- Scope-drift check: only M1–M6; preserve Web product/persistence names; no file behavior,
  compatibility alias, or unrelated Runtime changes
- Context checkpoint: moved files are present; final checkpoint will include generated
  descriptor identity, exact rename map, tests, absence evidence, and remaining CI status
