---
title: "Historical Memory Execution Policy Decisions"
created: 2026-10-04
tags: [memory, backend, observability, system-settings]
document_role: primary
document_type: adr
snapshot_id: memory-261004
---

# Historical Memory Execution Policy Decisions

- Snapshot: `memory-261004`
- Requirements: [memory-261004/REQ](../requirements/memory-261004-execution-policy.md)

## D1. Reuse model execution settings and the approved system cutoffs

The requester explicitly replaces the memory-261002 fixed execution budgets with main-Agent-equivalent model settings and only system-configurable turns/time. Keep the shared iteration core. Remove cumulative token, model-dispatch, tool-count, fixed per-call output-share, separate 70% input checkpoint, and working-draft capacity gates rather than retaining fallback flags. Read a direct-activation typed System Settings section at new-attempt admission. Use the shared core's nullable maximum-turn semantics and retain the existing ten-minute duration as the initial configurable value. Capture one policy for the claim, host and Job Runtime deadline.

Rejected: introducing environment-only limits, per-Agent controls, optional legacy budgets, another writer loop, or physical-request counts disguised as turns. These conflict with REQ-1/2. The 10k authored-document / 20k foreground product shape and scope authorization remain unchanged.

## D2. Separate actionable failure persistence from operational diagnostics

REQ-3 requires user-actionable/inspectable errors to be the only persisted failure codes. Internal authority/database errors, server-generated timeouts, execution cutoffs, validation bugs and unknown failures settle execution/retry state with a null failure code. Keep safe actionable provider authentication, permission, billing/quota and unavailable-selected-model codes. Lease/handover cancellation metadata records state, not a user error.

The registered Job Runtime is the terminal exception boundary: log uncaught handler exceptions once at ERROR with safe identities, concrete exception kind and origin traceback, then return its existing failed outcome. Domain services continue rethrowing; do not log-and-rethrow at each layer. Use the existing sanitization helper to retain frames without leaking provider bodies, memory or credentials. No direct Sentry SDK calls.

Rejected: storing every internal exception under `internal_execution_failed` or `authority_unconfirmed`, relying on no-progress warnings, or discarding retry/accounting state. A null internal error code is not a successful attempt.

## D3. Keep telemetry without budget authority

Physical dispatch identity, tool counts and usage remain observational. They fence current authority and settle exact dispatches idempotently but never stop valid execution because a memory-specific count/total was reached. Requested model output is nullable just like main; unknown provider usage remains explicit at each dispatch, never an inferred zero bill.

Database changes add the System Settings section enum, permit absent requested output tokens, and remove only private-draft capacity CHECKs. They do not grant new source authority or modify historical approved artifacts.

### D2 implementation clarification: terminal metadata after cutoff

Settling an already stopped attempt is separate from granting execution authority.
Exact active attempt, unit, generation and token comparisons permit bounded
metadata-only failure/retry settlement after the elapsed cutoff, preserving null
internal codes. They do not revive source/file/model/publication access, modify
completed outcomes or overwrite a new owner. This is derived from REQ-3's truthful
retry state and unchanged stale-owner/publication fences, not a new authority.

## Authority and execution

The requester required these corrections directly on 2026-10-04, including System Settings rather than Agent settings. All material outcomes above are fixed by that request and unchanged platform contracts. Implementation is authorized without a new design-interview pause. Fresh main baseline: `148835d55`. No live setting changes, migrations, restart, deploy or merge are authorized.
