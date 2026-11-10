---
title: "Scheduled Task Quiet Completion Decisions"
created: 2026-11-10
tags: [scheduled-task, architecture]
document_role: primary
document_type: adr
snapshot_id: quiet-261110
---

# Scheduled Task Quiet Completion Decisions

Authority: [quiet-261110/REQ](../requirements/quiet-261110-scheduled-completion.md).
The requester approved the presented product behavior and implementation on
2026-11-10. The following contracts record that scope and its necessary
consequences; they do not authorize new delivery modes or external actions.

## D1. Separate permission from occurrence notification

Store a Task-specific `allow_silent` boolean, copy it into the immutable occurrence
snapshot, and require `notify` plus a nullable `suppression_reason` at completion.
Keep a nonempty canonical `result` in all cases. Reject silent failed results,
files, absent permission and occurrences with explicit channel progress. Defaults
for existing persisted data preserve mandatory reporting. New internal callers
must choose values explicitly. Migration preserves historical occurrences/events
without a new schema version or legacy execution path.

Rejected: magic result strings, blank results, global mute and Routine conversion.
Those confuse execution with delivery or permit unintended loss of reports.

## D2. Settle once, suppress publication only

Retain existing fenced canonical terminal transaction, deterministic result
identity, one-time cleanup and recurring cursor advancement. Store the delivery
choice and reason with the canonical result. Skip terminal reply preparation for
silent results but preserve any required Tracker cleanup. Recovery returns the
first choice and does not replay external effects. No outbox, retry or fallback.

## D3. No automatic initial channel projection for eligible Tasks

Do not claim initial Trackers for quiet-permitted occurrences. Explicit meaningful
progress remains available and makes subsequent silent completion ineligible.
Keep required-report occurrences unchanged. Model guidance defines semantic
eligibility (no meaningful external change, no finding, no uncertainty); structural
validation does not pretend to prove semantic no-change.

## D4. Existing surfaces, inspectable non-notifying history

Use existing forms, provider controls, generated clients, typed terminal Event and
Session conversation. Render a quiet result as a collapsed completion detail, not
an empty assistant response. Completion notification consumers must not send a
push for that result. Do not add an independent history store or dashboard.
