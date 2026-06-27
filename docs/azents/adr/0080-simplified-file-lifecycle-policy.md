---
title: "ADR-0080: Simplified File Lifecycle Policy"
created: 2026-06-27
tags: [architecture, backend, engine, scheduler]
---
# ADR-0080: Simplified File Lifecycle Policy

## Context

ADR-0046 separated Attachment, Artifact, FilePart, and ModelFile lifecycles. The implemented follow-up kept three independent cleanup policies:

- ExchangeFile expires by time.
- Artifact expires by run age.
- ModelFile uses persistent run-age lifecycle stages: image degradation, unreachable, deleted.

A later implementation attempt moved those policies into a scheduler, but it preserved the complexity. That still left the scheduler calculating due work across sessions and kept lifecycle rules scattered across resource services, engine filters, lowerers, and run input preparation.

The product direction is simpler:

- ModelFile is only a model-context blob, not original-file storage.
- Artifact and ExchangeFile are temporary file-access resources, not long-term storage.
- Long-running work that needs file bytes should use runtime workspace files when a runtime/file toolkit is available.

This ADR supersedes the Artifact run-age and ModelFile persistent degradation/delete portions of ADR-0046 for future implementation. It does not change ADR-0046's separation between Attachment, Artifact, FilePart, and ModelFile, nor the rule that URI is a file-location address rather than an entity id.

## Decision

### ADR-0080-D1. Split file lifecycle into context-owned and TTL-owned classes

File lifecycle has two classes:

- **Context-owned**: ModelFile backing FilePart. Retention follows AgentSession model-input head reachability plus active run pins.
- **TTL-owned**: Artifact and ExchangeFile. Retention follows explicit `expires_at`.

The cleanup owner is the scheduler. Normal Agent run input preparation must not synchronously expire file resources.

### ADR-0080-D2. Artifact uses configurable TTL, default 7 days

Artifact no longer uses run-age retention. Artifact creation stores `expires_at`, calculated from configurable Artifact TTL. Default Artifact TTL is **7 days**.

`expires_after_run_index` is no longer the cleanup source of truth. It should be removed from current domain/API shapes unless a display-only migration phase temporarily needs it.

### ADR-0080-D3. ExchangeFile keeps TTL semantics with configurable retention

ExchangeFile remains TTL-owned. The existing default retention is preserved initially, but it must become configuration-owned rather than a hard-coded service constant.

The current implementation default is 30 days. If there is no deployment override, the new configuration should keep that behavior.

### ADR-0080-D4. ModelFile GC uses a session-level head cursor

ModelFile cleanup does not enqueue per-file candidates at head update time.

Each AgentSession stores a durable ModelFile GC cursor indicating the model-input head order through which ModelFile cleanup has completed. The scheduler periodically finds sessions where:

```text
model_file_gc_cursor_model_order < model_input_head_model_order
```

For each such session, the scheduler scans bounded event batches in:

```text
(model_file_gc_cursor_model_order, model_input_head_model_order]
```

The FileParts in that pruned range identify ModelFiles that are no longer current-head reachable.

After a range is fully processed, the scheduler advances the cursor to the current head order. The cursor is the durable progress marker, so failed or partial cleanup can retry without relying on ephemeral candidate enqueue.

### ADR-0080-D5. A ModelFile is referenced by exactly one durable FilePart event

ModelFile identity is single-event scoped. A `model_file_id` must not be reused across multiple durable events.

If the same source file is needed in a later event, a new ModelFile/FilePart is materialized. This invariant allows the cursor-based GC to avoid maintaining a current active-ref index. The scheduler only needs to protect active in-flight runs through pins.

### ADR-0080-D6. Active run pins protect ModelFiles during execution

A run may pin ModelFiles that it has materialized or may still materialize while executing. ModelFile GC must not delete a ModelFile that has an active pin.

Pins are released when the run reaches a terminal state. A repair path may clear stale pins for terminal runs.

### ADR-0080-D7. Persistent ModelFile degradation stages are removed

ModelFile cleanup no longer performs persistent image degradation such as `jpeg:1024` or `jpeg:300`, nor run-age transitions to `unreachable`.

Provider capability, image resizing, request byte limits, and placeholder fallback are handled during request-local materialization/lowering. If derivative caching is added later, derivatives inherit the parent ModelFile lifetime and are not a separate lifecycle state.

### ADR-0080-D8. Toolkit prompt owns TTL/import guidance

TTL guidance is toolkit-scoped rather than global.

A toolkit that exposes or consumes `exchange://` or `artifact://` URIs must state that those URIs are temporary and may expire.

A toolkit that exposes `import_file` must additionally instruct the agent to import files needed for later work into the runtime workspace and continue from the returned local path. This guidance must not imply permanent archival storage.

Artifact/Attachment lower metadata should show status and expiry facts, but should not repeat policy guidance.

### ADR-0080-D9. Blob deletion remains retryable and separate from access

Expired Artifact/ExchangeFile and deleted ModelFile access is denied by metadata state. Physical blob deletion success is recorded separately, for example with `blob_deleted_at`, and failed deletions are retried by later scheduler passes.

A physical blob that remains after a failed delete must not make an expired/deleted resource accessible again.

## Consequences

### Positive

- Artifact and ExchangeFile cleanup becomes simple indexed TTL work.
- ModelFile cleanup follows the session head model and is robust to compaction/head movement.
- The scheduler tracks ModelFile GC progress with a durable cursor instead of recalculating every session or relying on filter-time marks.
- Persistent ModelFile states shrink. The domain no longer needs run-age degradation/unreachable lifecycle as current behavior.
- Toolkit prompt ownership keeps runtime/file guidance close to the capability that provides it and avoids assuming every agent has a runtime.

### Negative / trade-offs

- Artifact availability changes from run-age semantics to time TTL semantics.
- ModelFile deletion depends on the single-event reference invariant and active run pin correctness.
- Request-local image resizing may repeat work unless derivative caching is added later.
- Session head movement must also store head model order so the scheduler can cheaply find cursor lag.

## Alternatives

### Move existing policies into scheduler unchanged

Rejected. This removes run-loop latency but keeps run-age Artifact and ModelFile degradation complexity. It also pushes the scheduler toward per-session latest-run calculations.

### Add a unified `file_resources` base table first

Rejected for the first phase. A base table may be useful later, but the primary simplification is policy-level. Introducing a generic file resource abstraction before simplifying policies would make the design harder to understand and implement.

### Delete every file when it falls behind head

Rejected. This fits ModelFile, but not Artifact or ExchangeFile. Artifact and ExchangeFile are user/agent file-access resources and should expire by TTL rather than compaction/head movement.

### Maintain a current active ModelFile reference index

Rejected for this policy because ModelFile has a single-event reference invariant. The scheduler scans the pruned range and uses active pins for in-flight safety. A current active-ref index can be added later only if ModelFile reuse across events becomes a requirement.

## Related documents

- [ADR-0046: Attachment, Artifact, and FilePart lifecycle](./0046-file-media-resource-lifecycle.md)
- [ADR-0049: User Input Boundary FilePart Materialization](./0049-user-input-bound-filepart-materialization.md)
- [ADR-0068: Periodic Execution Infrastructure](./0068-periodic-execution-infrastructure.md)
