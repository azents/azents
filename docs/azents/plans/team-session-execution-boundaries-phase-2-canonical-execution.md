---
title: "Team Session execution boundaries phase 2: pure broker and canonical execution"
created: 2026-07-24
tags: [session, authorization, broker, worker, execution, security]
---

# Team Session execution boundaries phase 2: pure broker and canonical execution

## Phase Execution Plan

- Phase: `2 — Pure broker and canonical execution snapshot`
- Branch/base: `feature/team-session-canonical-execution` → `feature/team-session-admission-provenance`
- PR boundary: routing-only Session broker contracts, owner-generation-first canonical execution loading, and Worker/RunExecutor durable identity boundary
- Requirements: [session-260724/REQ](../requirements/session-260724-team-session-execution-boundaries.md)
- ADR: [session-260724/ADR](../adr/session-260724-team-session-execution-boundaries.md)
- Design: [session-260724/DESIGN](../design/session-260724-team-session-execution-boundaries.md)
- Multi-phase plan: [Team Session execution boundaries implementation plan](./team-session-execution-boundaries-implementation-plan.md)

## Deliverables

- `SessionWakeUp` and `SessionStopSignal` contain only `session_id` and their discriminator.
- Broker encoders reject every legacy or rich payload rather than applying compatibility defaults.
- Every producer, Redis round trip, Worker path, recovery path, and testenv injection creates a pure Session routing signal.
- Session ownership generation is claimed before execution context construction.
- A single immutable canonical execution snapshot is loaded from Postgres after the claim.
- The snapshot validates active Session, Agent, Workspace, SessionAgent tree/context, root lineage, execution mode, claimed generation, and durable work identities.
- SessionRunner and RunExecutor derive Agent, Workspace, handle, execution mode, and durable work only from the snapshot.
- Mutable work processors retain their exact-row lock and generation revalidation. Input FIFO drift restarts preparation rather than using a stale head.

## Non-goals

- Removing generic Engine, Toolkit, Run, Tool, or Runtime User fields. That belongs to Phase 3.
- Session-owned file/output authority, migrations, replay/cutover, E2E, living-spec promotion, and cleanup.
- Any compatibility decoder, dual payload reader, nullable execution-User fallback, or broker-provided execution override.

## Boundary Contract

A broker signal means only that a Session may have durable work. It cannot select Agent, Workspace, handle, interface, prompt, execution mode, InputBuffer, command, Run, or continuation. After the durable owner-generation claim, the canonical loader validates and returns the complete execution identity and current work expectation. Every mutation must re-lock and revalidate the selected durable row. A changed FIFO head is stale preparation and must be reloaded.

## Workstreams

| Workstream | Owned paths | Output | Validation |
| --- | --- | --- | --- |
| Pure broker contract | `src/azents/broker/**`, all broker producers, testenv injection | Session-only signals and strict decoder | broker/Redis/producers tests |
| Canonical snapshot | `src/azents/worker/session/execution_snapshot.py`, Worker integration | immutable Postgres-derived execution identity | inactive/cross-boundary/tree/generation matrices |
| Worker and executor boundary | `src/azents/worker/session/**`, `src/azents/worker/run/executor.py` | snapshot-fed work dispatch and durable revalidation | takeover, command, recovery, continuation, stop, FIFO drift |
| Focused regression coverage | affected backend tests | pure-signal and override-proof coverage | Ruff, Pyright, focused pytest, diff check |

## Final Validation

- Focused Ruff format/check and Pyright from `python/apps/azents`.
- Focused pytest for broker, Redis, Worker, SessionRunner, RunExecutor, recovery, idle continuation, stop, and canonical snapshot loader matrices.
- `git diff --check`.
- Scope review confirming Phase 1 admission/provenance behavior remains unchanged and Phase 3+ work was not pulled forward.
