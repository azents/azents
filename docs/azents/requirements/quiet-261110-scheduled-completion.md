---
title: "Scheduled Task Quiet Completion Requirements"
created: 2026-11-10
implemented: 2026-11-10
tags: [scheduled-task, product, notifications]
document_role: primary
document_type: requirements
snapshot_id: quiet-261110
---

# Scheduled Task Quiet Completion Requirements

Snapshot: `quiet-261110` · Reference: `quiet-261110/REQ`

## Problem and Primary Context

A user schedules a periodic check and needs actionable findings without repetitive
no-change messages. The primary scenario is registering a scheduled check with
explicit permission to omit a report, executing the check, and retaining an
inspectable successful completion without sending an unnecessary message.

## Goals and Non-Goals

Preserve scheduled execution, required reports, failure visibility and execution
history while allowing explicitly authorized no-result completions. Do not add a
new history dashboard, global mute policy, execution scheduler, Routine migration,
new iOS Task editor, notification destination, delivery retry or fallback.

## Requirements

### REQ-1. Explicit Task-specific permission

Quiet completion is disabled for new and existing Tasks unless explicitly enabled.
Registration, replacement, listing and detail expose the permission. Chat creation
must not infer permission merely because the work is a check. Record the natural
language report/omission condition in the existing objective; ambiguous or
contradictory instructions retain reporting. Registration and explicit management
confirmations remain visible.

### REQ-2. Successful no-result occurrences only

Only an authorized occurrence which successfully completed its objective and
clearly satisfies the agreed omission condition may omit its result message.
Failures, incomplete checks, missing authority, uncertainty, meaningful external
changes, and files the user must receive require reporting. Internal bookkeeping
alone does not constitute a meaningful external change. Permission and the actual
per-occurrence decision are separate. Structural permission/outcome/file rules
must be enforced, while semantic report-worthiness remains model judgment and
must conservatively report when uncertain.

### REQ-3. Quiet from the start

Quiet-permitted Tasks do not automatically publish initial channel Trackers or
routine start/progress messages. Meaningful findings, actions or blockers may
be reported through the existing exact destination. An occurrence that has
already meaningfully reported progress must close with a short result rather
than silently abandoning that conversation. Do not delete prior messages to
simulate silence. Ordinary Task progress behavior is unchanged.

### REQ-4. Inspectable completion without notification

Retain the occurrence outcome, summary, omission reason and completion time in
the existing Session conversation. Show a compact expandable quiet-completion
state without an empty assistant answer, external result message or completion
push. Distinguish intentional omission from unsent, failed and uncertain delivery.
Retain the result after one-time Task cleanup. No separate history product.

### REQ-5. Lifecycle and recovery integrity

A started occurrence retains its original objective and permission when future
Task settings change or the definition is deleted. Explain this during editing.
Pre-start replacement follows the new settings. Stop/cancellation/interruption
are not quiet success. Recovered or duplicate completion retains the first
canonical decision without duplicate reports. Preserve existing authorization,
Session ownership, one-time cleanup, recurring progression and exact channel scope.

### REQ-6. Consistent existing surfaces and guidance

Extend existing web registration/edit/list/detail and channel registration/edit
surfaces with the same policy. Existing conversation renderers show a quiet
completion consistently. Include localized labels, keyboard-accessible controls,
responsive wrapping, preserved input on failed save and no default-value overwrite
during loading. Scheduled Task versus Routine guidance distinguishes mandatory
scheduled execution from opportunistic work selection, not notification obligation
alone. Do not change existing definitions automatically.

## Fixed Constraints and Assumptions

Schedule timestamps remain start triggers, not completion deadlines or exact
latency guarantees. Quiet completion does not imply lower execution cost. Model
judgment cannot be proved by a boolean policy field. No new authority to modify
external resources is granted by this feature.

## Confirmation

The requester approved the complete presented product behavior and requested
implementation on 2026-11-10 KST, including the final boundary that meaningful
external changes must be reported. This document transcribes that approved scope
without adding product behavior. Merge and deployment are not authorized.
