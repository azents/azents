---
title: "Work continuity across execution segments Design"
created: 2026-11-13
implemented: 2026-11-13
tags: [backend, engine, continuation]
document_role: primary
document_type: design
snapshot_id: continuation-261113
---

# Work continuity across execution segments Design

- Snapshot: `continuation-261113`
- Requirements: [continuation-261113/REQ](../requirements/continuation-261113-work-continuity.md)
- Decisions: [continuation-261113/ADR-D1](../adr/continuation-261113-work-continuity.md)
- Design revision: `2`

## Current behavior and gap

Scheduled occurrence settlement depends on both a special field on AgentRun and the cycle's current Run ID. Routine operations depend on a current Run ID and Run input provenance. TurnAction continuations are ordinary FIFO inputs but do not perform these domain-specific rebindings. Goal and Channel Work already keep their logical state independently of individual Runs.

## Design Authority

| ID | Material mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Server-maintained typed work context carried through every semantic continuation | REQ-1, REQ-2, ADR-D1 | decided |
| M2 | Domain work identity/state independent of an exclusive current Run; exact refs and live Session execution owner authorize mutation | REQ-1, REQ-3, ADR-D1; existing execution ownership | derived |
| M3 | Domain completion, scheduling, notification, Stop and archive/purge semantics remain independent and unchanged | REQ-2, REQ-3, REQ-5 | required |
| M4 | Data migration preserves already admitted work and canonical context, then removes replaced bindings | REQ-4, ADR-D1 | required |
| M5 | Retry, recovery, idle and bridge paths preserve authoritative context without reading model text; inter-agent input does not transfer foreign obligations | REQ-4, ADR-D1 | required |
| M6 | Explicit model-facing logical work selectors in applicable tools, continuation and existing compaction enrichment, with independent per-call recovery | REQ-6, REQ-7, ADR-D2; existing compaction commit/fail-open contracts | decided |

## Architecture and ownership

Keep canonical work state in existing owning domains. Introduce a typed internal execution work-context snapshot containing exact Scheduled cycle identities and Routine occurrence refs, plus provenance needed to distinguish Routine-only work from mixed ordinary input. This is an execution association, not another task lifecycle or scheduling authority.

Persist the snapshot on the Run instead of the Scheduled-only binding. A Run can carry several exact Scheduled and Routine occurrence refs; all refs are scoped to its canonical Session. Scheduled progress/completion explicitly select their cycle. Never overwrite another admitted cycle or impose a one-cycle-per-Run sequencing policy to retain an implicit selector. Analogous tool operations select the exact current logical item, retaining each domain's existing single/multiple-work policy.

Goal and Channel Work remain owned by their existing Session and Binding/work-cycle state. Do not mirror their mutable lifecycle into the execution snapshot. Their continuation paths must preserve any execution work context they continue, without inferring arbitrary active Scheduled/Routine work from Session membership.

One common repository operation merges a validated continuation source's context into its consuming execution. Bridge, idle and explicit retry paths call that operation; no per-domain current-host rewrite is performed. Initial Scheduled/Routine inputs add exact refs only after domain admission is validated. Ordinary user input and agent messages add no foreign refs and preserve the mixed-input provenance distinction.

## Domain mutation and lifecycle

Scheduled progress/result resolution reads the exact carried cycle ref and current canonical cycle. Routine context/result operations require the exact carried occurrence ref and matching current domain state. Current execution liveness, Session scope and owner-generation fences still apply. Domain state no longer requires equality with one current Run ID.

Archive/deletion preservation resolves the latest actual execution association of admitted work through the common context and ordinary active/idle boundary. A stale historical Run is not the preservation owner. Cancellation/Stop and archive exceptions remain unchanged; context membership alone does not revive terminal or cancelled work. Purge only proceeds once the existing preservation obligations are terminal.

Scheduled terminal submission must not terminate unrelated admitted Routine/Goal/Channel work. Preserve existing Scheduled-specific reporting and finish behavior only where no independent unfinished work is thereby abandoned.

## Data and migration

Replace AgentRun's Scheduled-specific binding with typed JSON work context. Remove current-host authority from Scheduled and Routine stored work state. Migration seeds exact refs from existing Run bindings, Routine occurrence state and canonical consumed inputs, including admitted bridge lineage; do not search model text. Preserve scope and mixed-input provenance.

Use one generated Alembic revision, keep the linear migration chain, test upgrade and data retention with admitted/started work, then remove the obsolete representation. Do not add schema-version modes, a permanent fallback or an operational data repair. Deployment is outside this task; rollback follows the repository's established migration constraints and must not silently discard new associations.

## Retry, recovery and compaction

Explicit retry carries the failed Run's canonical context but revalidates terminal domain state. Worker takeover resumes the stored context under the newer ordinary Session owner. Compaction summaries are never authority; the persisted snapshot survives transcript retention. Subagent result messages retain their original result identity and do not import child work scope into the parent.

## Interfaces and observability

Model-facing work-operation schemas expose/select exact logical identifiers under ADR-D2. Scheduled result arguments include cycle_id, and the initial/continuation renderers provide it with title and scheduled instant. Current active-work guidance shows only server-validated applicable identities. Analogous Goal/Channel Work identity selection must use their actual admission and replacement contracts, not introduce a generic lifecycle. No task scheduling policy, Toolkit identity, notification policy or new workflow product is added. Public generated clients are regenerated if existing API types are affected by the implementation. Logs and errors distinguish absent carried work from no-longer-active domain state without weakening execution authority checks.

### Compaction identity preservation

Use the existing on_compaction_summary pipeline to replace each owned work snapshot with canonical current work, including model-facing selectors. The Scheduled snapshot now includes cycle identity, deliberately changing the previous ID-omission contract. Preserve other internal identity redaction. Summary enrichment precedes bounded continuity, and continuity stays last. The owner/head/tail-validated marker/summary/head transaction remains the sole successful compaction boundary. Hook failure remains fail-open; failed/stale/cancelled compaction does not create a new context or selected identity. Model-request Toolkit preparation reads canonical work references rather than parsing generated summary text. Verify auto/manual/input-limit reconstruction paths before claiming reinjection coverage.

## Removal and Replacement

| Existing unit | Removal authority | Replacement | Boundary | Absence evidence |
| --- | --- | --- | --- | --- |
| AgentRun Scheduled-only binding | ADR-D1, REQ-1 | Common typed work context | Migration and all consumers | Production search, migrated catalog, tests |
| Scheduled/Routine current-Run equality as work authority | ADR-D1, REQ-1, REQ-3 | Exact refs + domain state + execution owner | Domain/lifecycle integration | Cross-kind continuation tests and stale-work tests |
| Domain-specific per-Run reassignment | ADR-D1 | Common context propagation | Promotion/retry integration | No remaining host-rebind paths |
| Run input provenance used as the sole continuing-work context | REQ-4 | Durable context snapshot with provenance | Migration/retention integration | Compaction/retention tests |

## Test Strategy

Start from the existing minimal Scheduled occurrence flow: trigger -> managed worktree creation -> work -> removal -> progress/result. Confirm settlement requires no recovery-only continuation. Keep costly E2E coverage minimal. Place combinations, multiple Routine refs, stale/foreign context, Stop/cancellation, archived preservation/purge, bridge ordering, duplicate delivery, retry/takeover, input mixing and transcript retention in repository and lower-layer tests.

Run Ruff, configured typing, focused repository/engine/worker tests and migration tests, then the normal PR CI at the final SHA. Use one read-only independent review after the integrated implementation is stable. Do not retry a flaky gate instead of investigating its cause.

## Feasibility and risks

Current Session owner fencing, domain state repositories and canonical input associations provide the required authority. Generic context persistence avoids relying on compacted transcript text. The main integration risk is archive/purge behavior, which currently joins domain host IDs directly to Run rows; that must be replaced and validated alongside terminal behavior, not deferred as cleanup.

Feasibility is verified by the full backend suite (14,851 passing tests), populated predecessor migration cases, exact-work repository regressions, and required public Scheduled E2E through a real Docker Runtime and managed-worktree create/remove continuations. The migration rejects unresolved transitive bridge provenance with whole-transaction rollback; retained normal lineage and unrelated terminal history are separately verified. Independent integrated review and targeted migration re-review closed the sole material finding. No production changes were required for development or acceptance.

## Design Approval

- Mode: Collaborative.
- Decision owner: requester.
- Direction authorized on: 2026-11-13, by explicit implementation request following the all-continuation separation proposal.
- Approved Design revision: 2 for the presented material direction.
- Approved authority IDs: M1, M2, M3, M4, M5, M6.
- Authorized scope: M1 through M5 as consequences of the previously presented separation, explicit work-context propagation, preserved execution checks and independent domain lifecycle; M6 was approved by the subsequent instruction to proceed with explicit model-visible IDs/continuation/spec-correct compaction and apply the same principle to analogous tools.
- Complete implementation feasibility: verified by the evidence above; this document does not claim requester approval of a new user-visible interface, operational mode, generic task lifecycle or broader authority.
