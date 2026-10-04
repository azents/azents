---
title: "Agentic Historical Memory Handover and Rehearsal"
created: 2026-10-04
tags: [memory, backend, operations, validation]
document_role: supporting
document_type: supporting-validation-report
snapshot_id: memory-261002
---

# Scope and Authority

This supporting execution record implements [memory-261002 Design revision 2](memory-261002-consolidated-history.md) M14/M15 and ADR D9/D13. It is not a new activation mode, deployment authorization, or claim that production has been migrated. No live cutover, rollback, migration, restart or infrastructure change was performed.

## Operator Prerequisites

Before any command below, the operator must independently verify and record:

1. A restorable database backup, the exact previous/new application images and additive-schema compatibility. Do not destructively downgrade the consolidation schema on rollback.
2. All affected execution admission is paused: API/request producers, External Channel gateways, scheduler, background jobs and Engine workers. Pausing only Historical discovery is insufficient.
3. Existing work has drained or been stopped through normal owner-fenced shutdown. No old process, replica, autoscaler or rollout controller can restart readers/writers during the operation. Record process/deployment absence, shutdown/drain evidence, image digests and KST times.
4. Interrupted root/child Run IDs, phases/statuses and conversation history are retained. No fabricated terminal events or destructive conversation cleanup is part of handover.
5. Admission remains closed throughout every bounded batch, result inspection and application image change. If interrupted, keep it closed and rerun the full action before allowing execution.

`--confirm-execution-quiesced` is the operator's explicit assertion of these external facts, not a database proof or an instruction for this CLI to stop infrastructure. Without it, the command rejects before configuration/DB access. PostgreSQL locks and consolidation generation/token fences protect database commits, but cannot stop old foreground processes; external coordination is mandatory.

## Forward Handover

From `python/apps/azents`, after additive migrations and the prerequisites above:

```console
uv run python -m azents.cli.memory_handover forward --confirm-execution-quiesced --batch-size 50
```

The command deletes only `memory/context_snapshot` automatic Toolkit State rows, fences retained internal owners, and hashes/enrolls already prepared canonical summaries in bounded transactions. It neither reruns Stage 1 extraction nor waits for six-hour admission. Saved records, source summaries, original history, other Toolkit State, Sessions and Runs remain intact.

Activate only the coherent new application after successful completion. Resume interrupted Runs through ordinary root preparation before lowering a new model request; children use their root boundary. Missing aggregates contribute no Historical body, while Saved and source lookup continue. Normal background discovery performs bounded consolidation. Verify owner/usage/privacy, current image consistency, Runtime absence and required E2E before reopening admission or declaring rollout complete. The command itself never activates an application.

## Explicit Rollback

Quiesce/fence new execution with the same prerequisites, then run the new image's operator command:

```console
uv run python -m azents.cli.memory_handover rollback --confirm-execution-quiesced --batch-size 50
```

This resets new automatic snapshots and fences internal owners while retaining additive tables inert. Restore the tested previous application image externally. Its normal preparation reconstructs previous-version snapshots from retained canonical Saved/source data. There is no in-process fallback, dual writer or compatibility decoder.

## Reactivation After Any Old-Code Interval

Old code cannot maintain new evidence/work identities or prove revoke/restore continuity. Always quiesce again and run:

```console
uv run python -m azents.cli.memory_handover reactivate --confirm-execution-quiesced --batch-size 50
```

Reactivation resets all automatic snapshots, fences owners, discards retained derived revisions/drafts/receipts/evidence and unpublished dispositions as a whole, rehashes current canonical summaries, advances content generation when needed, and reenrolls/reset-pends current exact-scope work. Identical body hashes do not preserve old aggregates. Current source authority and durable grants are independently rechecked by new work reads and publication. No new epoch authority or persisted rollout selector is introduced.

The destructive boundary is only derived consolidation state after all automatic references are reset. Canonical summaries, Saved rows and original conversations are preserved. Batches are retry-safe while admission stays closed; repeated reconciliation does not duplicate unchanged source enrollment or advance a matching content generation. A partial operation is not permission to activate either version.

## Rehearsal Evidence

Root-owned disposable PostgreSQL tests cover:

- Forward backfill with missing source generations/work and no Stage 1/model invocation; stable canonical bodies/timestamps, bounded pages and idempotent reenrollment.
- Explicit rollback with retained root/child interrupted Runs and history, owner fencing and additive bytes retained inert.
- Old-code direct summary writes without generation/outbox maintenance; reactivation detects changed hashes and invalidates even unchanged personal derived data.
- Snapshot reset ordering, fresh normal preparation, Saved preservation, no automatic source-packing fallback and stale-owner refusal.
- Exact selected-revision manifest authority, latest live reads, retained-reference collection and availability/grant continuity.

Commands, exact test counts, environment and final-SHA evidence are recorded in the feature's final QA report. These synthetic rehearsals establish application/database behavior, not a measured production pause duration or proof of actual old-worker absence. Live handover still requires separate operator approval and the externally recorded prerequisites above.
