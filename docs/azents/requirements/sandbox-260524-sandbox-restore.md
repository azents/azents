---
title: "Sandbox Restore Retry and Explicit Reset Historical Requirements Reconstruction"
created: 2026-05-24
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: sandbox-260524
historical_reconstruction: true
migration_source: "docs/azents/design/sandbox-explicit-restore-reset.md"
---

# Sandbox Restore Retry and Explicit Reset Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `sandbox-260524`
- Source: `docs/azents/design/sandbox-260524-sandbox-restore.md`
- Historical source date basis: `2026-05-24`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Session Workspace sandbox treats `/home/sandbox/**` as user-visible durable workspace. In K8s provider, S3/RustFS checkpoint is durable source; in Docker/provider-local home preservation provider, provider-local home directory is durable source.

Production incident revealed these problems.

1. Runtime could be recorded as `HIBERNATED` even when K8s Pod already disappeared and checkpoint could not be created.
2. When `HIBERNATED` runtime had no checkpoint or restore failed, API returned 200 response but UI did not sufficiently communicate failure state and options.
3. After failure, it was ambiguous whether `Start Sandbox` meant restore retry or empty sandbox initialization.
4. Even without failure, user should be able to explicitly reset Agent sandbox.

If generic start/resume API such as `Start Sandbox` implicitly creates empty sandbox, data loss can look like "successful recovery." Therefore, restore retry and reset must be separated as different user choices.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

- `START_SANDBOX` performs only idempotent start/resume/retry-restore.
- `RESET_SANDBOX` discards `/home/sandbox` durable state and creates fresh sandbox only when explicitly chosen by user.
- `RESTORE_FAILED` UI shows "retry" and "reset" as separate actions.
- Agent settings also provides sandbox reset button.
- K8s checkpoint provider and Docker/provider-local home preservation provider have same reset semantics.
- If backend is already `ABSENT`/`TERMINATING` before checkpoint creation, record `EXPIRED` instead of recording `HIBERNATED` without checkpoint.

## Non-goals

- Do not handle checkpoint object recovery, user-facing backup selection, or checkpoint history browser.
- Do not extend AgentRuntime schema with new state enum.
- reset confirmation phrase, audit event, and RBAC enhancement are not required scope of this PR.
- Do not add new protobuf command to provider protocol. Use existing delete command's `preserve_home=false` semantics for reset.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
