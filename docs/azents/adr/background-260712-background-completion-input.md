---
title: "Remove Deprecated Background Completion Input"
created: 2026-07-12
tags: [architecture, backend, engine, runtime, cleanup, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: background-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0134-remove-background-completion-input.md"
---

# background-260712/ADR: Remove Deprecated Background Completion Input

## Context

Azents still contains a background-task completion pipeline that can inject `background_completion` input buffers into a parent session. The dedicated Background feature is deprecated and has no active product use, but its registry, toolkit, runtime-coordination publication, worker queue, event kind, input-buffer kind, tests, and specifications remain in the codebase.

Keeping an unused asynchronous input source complicates the sequential input-buffer redesign and preserves recovery and idempotency machinery for behavior the product no longer exposes.

## Decision

Remove the deprecated Background feature and its completion-input pipeline instead of adapting it to the new buffer-preparation model.

The removal includes:

- `InputBufferKind.BACKGROUND_COMPLETION`;
- durable `EventKind.BACKGROUND_COMPLETION` and its payload mapping;
- background-completion live projection and title handling;
- `BackgroundTaskRegistry`, its completion injector, and the dedicated background-task toolkit;
- `BackgroundCompletionInput`, `WorkerInputQueue`, and DB/in-memory queue implementations used only by this pipeline;
- the background-completion publisher and its control-server loop;
- runtime-coordination candidate, claim, and published-state APIs used only for completion injection;
- dependency-injection fields and run contracts that exist only to pass the background registry;
- product tests, fixtures, and specifications for background tool calls and completion delivery.

This removal does not apply to unrelated uses of FastAPI `BackgroundTasks`, ordinary asyncio tasks used as implementation details, Runtime exec process lifecycle, or explicit `exec_command`/`write_stdin` process observation. Those mechanisms do not inject deprecated `background_completion` session input.

Use a new database migration for schema and PostgreSQL enum cleanup. Do not edit prior migrations. The migration removes stale pending `background_completion` buffers and stale durable `background_completion` events before replacing enum types without those values. No compatibility reader or legacy fallback is retained.

## Rejected Alternative

### Port background completion to sequential buffer preparation

This preserves code and protocol surface for a deprecated feature with no current caller. It would require defining turn effects, recovery, runtime publication, and UI behavior that the product no longer needs.

### Keep the enum values and dead implementation for compatibility

Dead values continue to expand exhaustive unions and make future processors, lowerers, and migrations account for an unsupported input source.

## Consequences

- The input-buffer kind review continues without `background_completion`.
- Runtime and worker coordination lose the dedicated background completion publication path.
- Historical data of the removed kind is deleted during migration rather than preserved through legacy decoding.
- Background-specific specs are deleted or rewritten to describe only remaining supported runtime/process behavior.
- Exhaustive event and buffer-kind consumers become smaller and fail type checking if stale branches remain.

## References

- [drain-260712/ADR: Drain Input Buffers Sequentially Before Turn Start](./drain-260712-drain-input-buffers-before-turn-start.md)

## Migration provenance

- Historical source filename: `0134-remove-background-completion-input.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
