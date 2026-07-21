---
title: "Expose Typed Actionable Profile Resolution Failures"
created: 2026-07-10
tags: [architecture, backend, chat, errors, routing, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: typed-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0120-typed-profile-resolution-failures.md"
---

# typed-260710/ADR: Expose Typed Actionable Profile Resolution Failures

## Context

Strict run-time target resolution intentionally does not fall back when a requested label disappears, routing cannot choose an eligible model, or an explicit effort becomes unsupported. A generic system-error string cannot reliably drive user recovery, message provenance details, or operational grouping. Rejecting only at enqueue time is insufficient because configuration can change while an input waits in FIFO order.

The UI must remain actionable without exposing credentials, decrypted configuration, or unnecessary internal provider diagnostics.

## Decision

Persist a typed profile-resolution failure code on the failed AgentRun while retaining its requested provenance and leaving resolved provenance null. Initial codes are:

- `model_target_not_found`;
- `model_target_resolution_failed`;
- `reasoning_effort_unsupported`.

Project each code to localized, user-safe chat content that names the requested target or effort when useful and explains the available recovery path. Render the error as a failed-run surface associated with the triggering user message and provide:

- **Edit message**, which restores the original message and requested profile and permits choosing another target or effort;
- **Retry**, which preserves the original requested profile and resolves it again against current routing configuration.

Run-start profile resolution failures become terminal immediately and do not enter the provider-call automatic retry loop because no resolved run profile has been activated. Manual Retry never substitutes the Agent default, another target, or another explicit effort. It can succeed after target configuration is restored or a transient routing failure clears.

The user-message timestamp metadata continues to display the stable requested target label. Its hover/focus/touch detail reports the failed resolution state and safe failure reason. It does not invent a resolved model.

Structured operator logs include run/session/agent identifiers, requested target and effort, failure code, safe internal reason identifiers, and relevant integration ID. They never include credentials or decrypted provider configuration. Detailed internal exceptions remain server-side and are not copied directly into public error messages.

## Rejected options

### Emit only a generic system error

The frontend could not distinguish profile failures or present the correct recovery actions without parsing unstable text.

### Reject the message only during API acceptance

A valid target can disappear or become unsatisfied while queued. Authoritative run-time failure still needs durable provenance.

### Automatically choose another model or effort

This hides failed user intent and violates strict resolution.

### Allow Retry to override the profile

Retry preserves the original request. Profile changes belong to Edit or a new message.

## Consequences

- AgentRun gains typed profile failure data usable by API projections and observability.
- Resolution failures create terminal failed runs with requested provenance and no resolved snapshot.
- Chat error rendering becomes code-driven and localized instead of parsing backend prose.
- Edit can expose an invalid original selection long enough for the user to replace it.
- Retry remains useful after configuration repair while staying semantically faithful to the original request.

## Migration provenance

- Historical source filename: `0120-typed-profile-resolution-failures.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
